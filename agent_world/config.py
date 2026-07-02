from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_INVOCATION_BACKEND = "llm"
DEFAULT_IMPLEMENTATION_INVOCATION_BACKEND = "codex_sdk"
DEFAULT_OPENAI_BASE_URL = "https://blog.r78xoaxrk.nyat.app:50903/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_MODEL_CANDIDATES = [
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.5",
]
DEFAULT_INVOCATION_NETWORK = True
DEFAULT_INVOCATION_TIMEOUT_MS = 60000
DEFAULT_INVOCATION_MAX_TOKENS = 4096
DEFAULT_INVOCATION_MAX_ATTEMPTS = 3
DEFAULT_CODE_REPAIR_THREAD_MODE = "stateless"
DEFAULT_CODEX_SANDBOX = "workspace-write"
DEFAULT_CONFIG_RELATIVE_PATH = Path("config") / "agent-world.default.yaml"
SEMANTIC_INVOCATION_PROFILE = "semantic"
IMPLEMENTATION_INVOCATION_PROFILE = "implementation"
INVOCATION_PROFILE_STAGES = [
    "PLAN",
    "S0",
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "IMPLEMENT",
]
PIPELINE_STAGES = [
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
DEFAULT_STAGE_INVOCATION_PROFILES = {stage: SEMANTIC_INVOCATION_PROFILE for stage in INVOCATION_PROFILE_STAGES}
DEFAULT_STAGE_INVOCATION_PROFILES["IMPLEMENT"] = IMPLEMENTATION_INVOCATION_PROFILE


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
class InvocationProfileConfig:
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
    backend_auth: bool
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
    research: ResearchConfig
    invocation_profiles: dict[str, InvocationProfileConfig]
    stage_invocation_profiles: dict[str, str]
    config_path: str = ""

    def profile_for_stage(self, stage: str) -> InvocationProfileConfig:
        if stage not in self.stage_invocation_profiles:
            raise KeyError(f"Stage {stage} has no invocation profile because it is deterministic or unknown.")
        profile_id = self.stage_invocation_profiles[stage]
        if profile_id not in self.invocation_profiles:
            raise KeyError(f"Stage {stage} references unknown invocation profile: {profile_id}")
        return self.invocation_profiles[profile_id]

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "research": asdict(self.research),
            "invocation_profiles": {
                profile_id: asdict(profile)
                for profile_id, profile in self.invocation_profiles.items()
            },
            "stage_invocation_profiles": dict(self.stage_invocation_profiles),
            "config_path": self.config_path,
        }


def load_agent_world_config(env: Mapping[str, str] | None = None) -> AgentWorldConfig:
    values = os.environ if env is None else env
    file_config, config_path = _load_config_file(values)
    semantic = _resolve_invocation_profile(
        values,
        file_config,
        profile_id=SEMANTIC_INVOCATION_PROFILE,
        base=None,
        default_backend_kind=DEFAULT_INVOCATION_BACKEND,
    )
    implementation = _resolve_invocation_profile(
        values,
        file_config,
        profile_id=IMPLEMENTATION_INVOCATION_PROFILE,
        base=semantic,
        default_backend_kind=_implementation_default_backend_kind(file_config),
    )
    profiles = {
        SEMANTIC_INVOCATION_PROFILE: semantic,
        IMPLEMENTATION_INVOCATION_PROFILE: implementation,
    }
    for profile_id in sorted(_configured_profile_ids(file_config) - set(profiles)):
        base_profile = profiles.get(_profile_parent(file_config, profile_id), semantic)
        profiles[profile_id] = _resolve_invocation_profile(
            values,
            file_config,
            profile_id=profile_id,
            base=base_profile,
            default_backend_kind=base_profile.backend_kind,
        )
    return AgentWorldConfig(
        research=_load_research_config(file_config=file_config),
        invocation_profiles=profiles,
        stage_invocation_profiles=_stage_invocation_profiles(file_config),
        config_path=config_path,
    )


def load_research_config(env: Mapping[str, str] | None = None) -> ResearchConfig:
    values = os.environ if env is None else env
    file_config, _ = _load_config_file(values)
    return _load_research_config(file_config=file_config)


def _load_research_config(*, file_config: Mapping[str, Any] | None = None) -> ResearchConfig:
    research = _mapping_at(file_config or {}, ["research"])
    return ResearchConfig(
        backend=str(research.get("backend", "jina")),
        searxng_url=str(research.get("searxng_url", "")),
        jina_search_url=str(research.get("jina_search_url", "https://s.jina.ai")),
        jina_reader_url=str(research.get("jina_reader_url", "https://r.jina.ai")),
        jina_api_key_env=_jina_api_key_env(research),
        process_command=str(research.get("process_command", "")),
        max_queries=max(1, int(research.get("max_queries", "5"))),
        max_results=max(1, int(research.get("max_results", "10"))),
    )


def _jina_api_key_env(research: Mapping[str, Any] | None = None) -> str:
    configured = (research or {}).get("jina_api_key_env") or (research or {}).get("api_key_env")
    if configured:
        return str(configured)
    return "JINA_API_KEY"


def _resolve_invocation_profile(
    values: Mapping[str, str],
    file_config: Mapping[str, Any],
    *,
    profile_id: str,
    base: InvocationProfileConfig | None,
    default_backend_kind: str,
) -> InvocationProfileConfig:
    profile = _profile_mapping(file_config, profile_id)
    backend_kind = str(profile.get("backend_kind", default_backend_kind))
    base_url = _base_url_value(values, profile.get("base_url", base.base_url if base else DEFAULT_OPENAI_BASE_URL))
    model = str(profile.get("model", base.model if base else DEFAULT_OPENAI_MODEL))
    smoke_model = str(profile.get("smoke_model", model))
    candidates_raw = profile.get("model_candidates", base.model_candidates if base else DEFAULT_OPENAI_MODEL_CANDIDATES)
    model_candidates = _model_candidates(candidates_raw)
    api_version = str(profile.get("api_version", _infer_api_version(base_url, backend_kind)))
    api_key_env = str(profile.get("api_key_env", base.api_key_env if base else "OPENAI_API_KEY"))
    auth_env_refs = _auth_env_refs(api_key_env)
    command_value = _command_value(profile, backend_kind, base)
    allowlist_value = str(profile.get("allowlist_value", base.allowlist_value if base else ""))
    command_cwd = str(profile.get("command_cwd", base.command_cwd if base else "."))
    return InvocationProfileConfig(
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
        backend_auth=bool(profile.get("backend_auth", base.backend_auth if base else False)),
        command_value=command_value,
        allowlist_value=allowlist_value,
        command_cwd=command_cwd,
        timeout_ms=int(profile.get("timeout_ms", base.timeout_ms if base else DEFAULT_INVOCATION_TIMEOUT_MS)),
        max_attempts=int(profile.get("max_attempts", base.max_attempts if base else DEFAULT_INVOCATION_MAX_ATTEMPTS)),
        max_tokens=int(profile.get("max_tokens", base.max_tokens if base else DEFAULT_INVOCATION_MAX_TOKENS)),
        network=bool(profile.get("network", base.network if base else DEFAULT_INVOCATION_NETWORK)),
        codex_sandbox=str(profile.get("codex_sandbox", base.codex_sandbox if base else DEFAULT_CODEX_SANDBOX)),
        code_repair_thread_mode=_code_repair_thread_mode(str(profile.get("code_repair_thread_mode", base.code_repair_thread_mode if base else DEFAULT_CODE_REPAIR_THREAD_MODE))),
    )


def _implementation_default_backend_kind(file_config: Mapping[str, Any]) -> str:
    profile = _profile_mapping(file_config, IMPLEMENTATION_INVOCATION_PROFILE)
    if profile.get("backend_kind"):
        return str(profile["backend_kind"])
    return DEFAULT_IMPLEMENTATION_INVOCATION_BACKEND


def _command_value(
    profile: Mapping[str, Any],
    backend_kind: str,
    base: InvocationProfileConfig | None,
) -> str:
    default = str(profile.get("command_value", base.command_value if base else ""))
    if backend_kind in {"codex_cli", "codex_cli_runner"}:
        return str(profile.get("codex_cmd", default))
    return str(default or profile.get("code_agent_cmd", ""))


def _stage_invocation_profiles(file_config: Mapping[str, Any]) -> dict[str, str]:
    stage_config = _mapping_at(file_config, ["stages"])
    if stage_config:
        default_profile = str(stage_config.get("default_invocation_profile", SEMANTIC_INVOCATION_PROFILE))
        bindings = {stage: default_profile for stage in INVOCATION_PROFILE_STAGES}
    else:
        bindings = dict(DEFAULT_STAGE_INVOCATION_PROFILES)
    configured = stage_config.get("invocation_profiles", {})
    if isinstance(configured, Mapping):
        for stage, profile_id in configured.items():
            stage_name = str(stage).upper()
            if stage_name not in INVOCATION_PROFILE_STAGES:
                raise ValueError(f"Stage {stage_name} cannot declare an invocation profile; deterministic stages do not invoke backends.")
            bindings[stage_name] = str(profile_id)
    for key, value in stage_config.items():
        stage_name = str(key).upper()
        if stage_name in INVOCATION_PROFILE_STAGES and isinstance(value, str):
            bindings[stage_name] = value
        elif stage_name in PIPELINE_STAGES:
            raise ValueError(f"Stage {stage_name} cannot declare an invocation profile; deterministic stages do not invoke backends.")
    return bindings


def _load_config_file(values: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    path_text = str(values.get("AGENT_WORLD_CONFIG", "")).strip()
    if not path_text:
        path = Path(__file__).resolve().parents[1] / DEFAULT_CONFIG_RELATIVE_PATH
        if not path.is_file():
            return {}, ""
        path_text = str(path)
    else:
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
    profiles = _mapping_at(file_config, ["invocation_profiles"])
    return {str(profile_id) for profile_id in profiles}


def _profile_mapping(file_config: Mapping[str, Any], profile_id: str) -> dict[str, Any]:
    profiles = _mapping_at(file_config, ["invocation_profiles"])
    value = profiles.get(profile_id, {})
    return dict(value) if isinstance(value, Mapping) else {}


def _profile_parent(file_config: Mapping[str, Any], profile_id: str) -> str:
    parent = _profile_mapping(file_config, profile_id).get("inherits", SEMANTIC_INVOCATION_PROFILE)
    return str(parent or SEMANTIC_INVOCATION_PROFILE)


def _mapping_at(value: Mapping[str, Any], path: list[str]) -> dict[str, Any]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key, {})
    return dict(current) if isinstance(current, Mapping) else {}


def _config_value(file_config: Mapping[str, Any], path: list[str], default: Any) -> Any:
    current: Any = file_config
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def _base_url_value(values: Mapping[str, str], configured: Any) -> str:
    return str(values.get("OPENAI_BASE_URL") or configured or DEFAULT_OPENAI_BASE_URL)


def _auth_env_refs(api_key_env: str) -> list[str]:
    return [api_key_env] if api_key_env else []


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

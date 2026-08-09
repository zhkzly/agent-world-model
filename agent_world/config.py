"""Only the endpoints and credential handles needed by Direct."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Safe configuration failure; never includes a secret value."""


@dataclass(frozen=True, slots=True)
class ChatRoute:
    model: str
    base_url: str
    api_key_env: str


@dataclass(frozen=True, slots=True)
class AgentRoute:
    model: str
    base_url: str
    api_key_env: str


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    search_url: str
    reader_url: str
    api_key_env: str


@dataclass(frozen=True, slots=True)
class FoundrySettings:
    state_root: Path
    direct_primary: ChatRoute
    direct_fallback: ChatRoute
    agent_primary: AgentRoute
    agent_fallback: AgentRoute
    research: ResearchSettings


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"config_{name}_object_required")
    return value


def _only(data: dict[str, Any], allowed: set[str], name: str) -> None:
    if set(data).difference(allowed):
        raise ConfigurationError(f"config_{name}_unknown_field")


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ConfigurationError(f"config_{name}_required")
    return value.strip()


def _url(value: object, name: str) -> str:
    url = _text(value, name)
    if not url.startswith(("http://", "https://")) or any(char in url for char in "@?#"):
        raise ConfigurationError(f"config_{name}_invalid_url")
    return url.rstrip("/")


def _chat_route(value: object, name: str) -> ChatRoute:
    data = _mapping(value, name)
    _only(data, {"model", "base_url", "api_key_env"}, name)
    return ChatRoute(
        model=_text(data.get("model"), f"{name}_model"),
        base_url=_url(data.get("base_url"), f"{name}_base_url"),
        api_key_env=_text(data.get("api_key_env"), f"{name}_api_key_env", empty=True),
    )


def _agent_route(value: object, name: str) -> AgentRoute:
    data = _mapping(value, name)
    _only(data, {"model", "base_url", "api_key_env"}, name)
    return AgentRoute(
        model=_text(data.get("model"), f"{name}_model"),
        base_url=_url(data.get("base_url"), f"{name}_base_url"),
        api_key_env=_text(data.get("api_key_env"), f"{name}_api_key_env", empty=True),
    )


def load_settings(source: Path | str) -> FoundrySettings:
    path = Path(source)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError("config_unreadable") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError("config_invalid_toml") from exc
    _only(data, {"foundry", "direct", "agent", "research"}, "top_level")

    foundry = _mapping(data.get("foundry"), "foundry")
    _only(foundry, {"state_root"}, "foundry")
    state_root = Path(_text(foundry.get("state_root"), "foundry_state_root"))
    if not state_root.is_absolute():
        state_root = path.parent / state_root

    direct = _mapping(data.get("direct"), "direct")
    _only(direct, {"primary", "fallback"}, "direct")
    agent = _mapping(data.get("agent"), "agent")
    _only(agent, {"primary", "fallback"}, "agent")
    research = _mapping(data.get("research"), "research")
    _only(research, {"search_url", "reader_url", "api_key_env"}, "research")

    return FoundrySettings(
        state_root=state_root,
        direct_primary=_chat_route(direct.get("primary"), "direct_primary"),
        direct_fallback=_chat_route(direct.get("fallback"), "direct_fallback"),
        agent_primary=_agent_route(agent.get("primary"), "agent_primary"),
        agent_fallback=_agent_route(agent.get("fallback"), "agent_fallback"),
        research=ResearchSettings(
            search_url=_url(research.get("search_url"), "research_search_url"),
            reader_url=_url(research.get("reader_url"), "research_reader_url"),
            api_key_env=_text(research.get("api_key_env"), "research_api_key_env", empty=True),
        ),
    )


def credential_from_environment(name: str) -> str | None:
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError("credential_missing")
    return value

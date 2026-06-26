from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from awmx.artifacts.schemas import ValidationError, WorkflowSpec


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValidationError(f"{path} must contain a mapping")
    return payload


def load_agent_world_config(path: Path | str) -> dict[str, Any]:
    payload = _load_yaml(Path(path))
    for field_name in ("id", "version", "created_at", "source", "metadata", "paths", "policies"):
        if field_name not in payload:
            raise ValidationError(f"base config missing required field: {field_name}")
    if not isinstance(payload["paths"], dict):
        raise ValidationError("paths must be a mapping")
    if not isinstance(payload["policies"], dict):
        raise ValidationError("policies must be a mapping")
    for path_key in ("config_root", "output_root"):
        if not isinstance(payload["paths"].get(path_key), str) or not payload["paths"][path_key]:
            raise ValidationError(f"paths.{path_key} must be a non-empty string")
    return payload


def load_workflow_config(path: Path | str) -> WorkflowSpec:
    return WorkflowSpec.from_dict(_load_yaml(Path(path)))


def resolve_config_path(config: dict[str, Any], config_path: Path | str, value: str) -> Path:
    return _resolve_path(value, _project_root_for_config(config, Path(config_path)))


def resolve_runs_root(config: dict[str, Any], config_path: Path | str) -> Path:
    paths = config.get("paths", {})
    project_root = _project_root_for_config(config, Path(config_path))
    runs_root = paths.get("runs_root")
    if isinstance(runs_root, str) and runs_root:
        return _resolve_path(runs_root, project_root)

    output_root = paths.get("output_root")
    if not isinstance(output_root, str) or not output_root:
        raise ValidationError("paths.output_root must be a non-empty string")
    return _resolve_path(output_root, project_root) / "runs"


def _project_root_for_config(config: dict[str, Any], config_path: Path) -> Path:
    config_path = config_path.resolve()
    config_dir = config_path.parent
    config_root = config.get("paths", {}).get("config_root")
    if not isinstance(config_root, str) or not config_root:
        return config_dir

    root_path = Path(config_root)
    if root_path.is_absolute():
        return root_path.parent

    root_parts = root_path.parts
    config_parts = config_dir.parts
    if len(config_parts) >= len(root_parts) and config_parts[-len(root_parts):] == root_parts:
        return Path(*config_parts[:-len(root_parts)])
    return config_dir


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from awmx.artifacts.schemas import ValidationError, WorkflowSpec
from awmx.workflow.spec import validate_workflow_spec


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
    workflow = WorkflowSpec.from_dict(_load_yaml(Path(path)))
    return validate_workflow_spec(workflow)

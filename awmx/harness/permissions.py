from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from awmx.artifacts.schemas import ValidationError


@dataclass
class PermissionGate:
    allowed_action_kinds: set[str]
    writable_roots: list[Path] = field(default_factory=list)
    required_path_fields: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "command": ("cwd",),
            "write_file": ("path",),
            "file_edit": ("path",),
        }
    )

    def __post_init__(self) -> None:
        self.writable_roots = [Path(root).resolve() for root in self.writable_roots]

    def authorize(self, action: dict[str, Any]) -> dict[str, Any]:
        decision = self.decide(action)
        if not decision["allowed"]:
            raise ValidationError(decision["reason"])
        return decision

    def decide(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = action.get("kind")
        if kind not in self.allowed_action_kinds:
            return {
                "allowed": False,
                "kind": kind,
                "reason": f"permission denied for action kind: {kind}",
            }

        decision = {"allowed": True, "kind": kind}
        for field_name in self.required_path_fields.get(kind, ()):
            if action.get(field_name) is None:
                return {
                    "allowed": False,
                    "kind": kind,
                    "reason": f"permission denied: {kind} requires {field_name}",
                }

        for field_name in ("path", "cwd"):
            path_value = action.get(field_name)
            if path_value is None:
                continue
            normalized = self._normalize_allowed_path(kind, field_name, path_value)
            if not normalized["allowed"]:
                return normalized
            decision[field_name] = normalized["path"]

        for field_name in ("read_paths", "write_paths"):
            path_values = action.get(field_name)
            if path_values is None:
                continue
            if not isinstance(path_values, list):
                return {
                    "allowed": False,
                    "kind": kind,
                    "reason": f"{field_name} must be a list of paths",
                }
            normalized_paths = []
            for path_value in path_values:
                normalized = self._normalize_allowed_path(kind, field_name, path_value)
                if not normalized["allowed"]:
                    return normalized
                normalized_paths.append(normalized["path"])
            decision[field_name] = normalized_paths

        return decision

    def _normalize_allowed_path(self, kind: str, field_name: str, path_value: Any) -> dict[str, Any]:
        try:
            path = Path(path_value).resolve()
        except (TypeError, ValueError, OSError):
            return {
                "allowed": False,
                "kind": kind,
                "reason": f"{field_name} must be a valid path string",
            }

        if not self.writable_roots:
            return {
                "allowed": False,
                "kind": kind,
                field_name: str(path),
                "reason": f"permission denied for {field_name} without writable root: {path}",
            }
        if not any(self._is_within(path, root) for root in self.writable_roots):
            return {
                "allowed": False,
                "kind": kind,
                field_name: str(path),
                "reason": f"permission denied for {field_name}: {path}",
            }
        return {
            "allowed": True,
            "kind": kind,
            "path": str(path),
        }

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

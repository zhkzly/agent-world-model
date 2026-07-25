"""Fresh normal semantic-prefix execution for staged downstream testing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agent_world.config import FoundryConfig
from agent_world.contracts import PermissionScope, V2Contract

from .direct_runner import SemanticPrefixRun


class SemanticPrefixError(RuntimeError):
    """A safe machine-readable semantic-prefix setup failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SemanticPrefixResult(V2Contract):
    """CLI projection of a fresh normal prefix and its safe observe scene."""

    state_root: str
    scope_id: str
    run: SemanticPrefixRun
    scene: dict[str, object]
    diagnostic_only: Literal[False] = False
    release_attempted: Literal[False] = False


@dataclass(slots=True)
class SemanticPrefixRunner:
    """Create one fresh state root and run the normal Direct semantic prefix."""

    config: FoundryConfig
    state_parent: Path | None = None

    async def run(
        self,
        *,
        need: str,
        request_id: str | None = None,
        permissions: PermissionScope | None = None,
    ) -> SemanticPrefixResult:
        state_root = self._new_state_root()

        # Import locally to keep the production application composition root
        # independent from this staged command wrapper.
        from agent_world.app import build_application

        app = build_application(self.config.model_copy(update={"state_root": state_root}))
        outcome = await app.controller.run_semantic_prefix(
            need,
            request_id=request_id,
            permissions=permissions,
        )
        try:
            scene = app.controller.scene_projector.rebuild(
                outcome.scope_id,
                run_id=outcome.run_id,
            )
        except Exception as exc:
            raise SemanticPrefixError(
                "semantic_prefix_scene_unavailable",
                "semantic-prefix scene could not be rebuilt from durable facts",
            ) from exc
        return SemanticPrefixResult(
            state_root=str(state_root.resolve(strict=True)),
            scope_id=outcome.scope_id,
            run=outcome,
            scene={
                "index": scene.index.model_dump(mode="json"),
                "coordinates": [item.model_dump(mode="json") for item in scene.coordinates],
            },
        )

    def _new_state_root(self) -> Path:
        parent = self.state_parent or self._default_state_parent()
        candidate = parent.expanduser()
        if ".agent-world-live" in candidate.parts:
            raise SemanticPrefixError(
                "semantic_prefix_reserved_live_parent",
                "normal semantic-prefix state cannot use the reserved live directory",
            )
        if candidate.exists() and candidate.is_symlink():
            raise SemanticPrefixError(
                "semantic_prefix_parent_symlink",
                "semantic-prefix parent cannot be a link",
            )
        try:
            candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
            candidate.chmod(0o700)
        except OSError as exc:
            raise SemanticPrefixError(
                "semantic_prefix_parent_unavailable",
                "semantic-prefix parent is unavailable",
            ) from exc
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        state_root = candidate / (f"semantic-prefix-{timestamp}-{uuid.uuid4().hex[:12]}")
        if state_root.exists() or state_root.is_symlink():
            raise SemanticPrefixError(
                "semantic_prefix_state_conflict",
                "fresh semantic-prefix state root already exists",
            )
        return state_root

    def _default_state_parent(self) -> Path:
        for candidate in self.config.state_root.parents:
            if candidate.name == ".agent-world-live":
                return candidate.parent / ".agent-world-staged"
        return Path.cwd() / ".agent-world-staged"


__all__ = [
    "SemanticPrefixError",
    "SemanticPrefixResult",
    "SemanticPrefixRunner",
]

from __future__ import annotations

import json
from pathlib import Path

from awmx.artifacts.ids import validate_storage_id
from awmx.artifacts.schemas import BaseArtifact, SCHEMA_REGISTRY, ValidationError


class ArtifactRegistry:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write(self, artifact: BaseArtifact) -> Path:
        artifact_type = artifact.artifact_type
        artifact_id = validate_storage_id(artifact.id, "artifact.id")
        artifact_dir = self.root / f"{artifact_type}s"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{artifact_id}.json"
        artifact_path.write_text(
            json.dumps(artifact.to_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return artifact_path

    def read(self, artifact_type: str, artifact_id: str) -> BaseArtifact:
        schema_cls = SCHEMA_REGISTRY.get(artifact_type)
        if schema_cls is None:
            raise ValidationError(f"unknown artifact type: {artifact_type}")
        artifact_id = validate_storage_id(artifact_id, "artifact_id")

        artifact_path = self.root / f"{artifact_type}s" / f"{artifact_id}.json"
        if not artifact_path.exists():
            raise FileNotFoundError(artifact_path)

        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        return schema_cls.from_dict(payload)

"""Semantic and implementation lineage are deliberately independent."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract


class IdentityDecision(V2Contract):
    decision_id: Identifier
    target_kind: Literal["package_revision", "new_package"]
    boundary_before_hash: ContentHash | None = None
    boundary_after_hash: ContentHash
    changed_boundary_dimensions: tuple[Identifier, ...] = ()
    rationale: NonEmptyStr
    confidence: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def validate_boundary_change(self) -> IdentityDecision:
        if self.target_kind == "package_revision" and self.changed_boundary_dimensions:
            raise ValueError("package_revision cannot declare changed WorldBoundary dimensions")
        return self


class SemanticLineage(V2Contract):
    lineage_id: Identifier
    semantic_parent_refs: tuple[ArtifactRef, ...] = ()
    clue_refs: tuple[ArtifactRef, ...] = ()
    evidence_refs: tuple[ArtifactRef, ...] = ()
    operator_id: Identifier
    operator_version: NonEmptyStr
    operator_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    seed: Annotated[int, Field(ge=0)]
    tool_contract_set_before_hash: ContentHash | None = None
    tool_contract_set_after_hash: ContentHash
    world_spec_before_hash: ContentHash | None = None
    world_spec_after_hash: ContentHash
    semantic_delta_hash: ContentHash
    identity_decision: IdentityDecision


class ImplementationLineage(V2Contract):
    lineage_id: Identifier
    source_snapshot_refs: tuple[ArtifactRef, ...] = ()
    parent_workspace_refs: tuple[ArtifactRef, ...] = ()
    builder_profile_hash: ContentHash
    backend: Identifier
    model: NonEmptyStr
    session_id: Identifier
    dependency_lock_hash: ContentHash
    implementation_contract_ref: ArtifactRef


class PackageLineage(V2Contract):
    semantic: SemanticLineage
    implementation: ImplementationLineage


__all__ = [
    "IdentityDecision",
    "ImplementationLineage",
    "PackageLineage",
    "SemanticLineage",
]

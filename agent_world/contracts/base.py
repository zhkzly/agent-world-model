"""Shared primitives for the Agent World v2 component contracts.

Contracts are intentionally strict and serialise deterministically.  They are
the only values that may cross component boundaries; provider SDK objects and
mutable implementation state must stay behind their adapters.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

SCHEMA_VERSION: Literal["v2"] = "v2"

type Identifier = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
type ContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
type NonEmptyStr = Annotated[str, Field(min_length=1)]
type JsonObject = dict[str, JsonValue]


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes for a contract or JSON-compatible value."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class StrictModel(BaseModel):
    """A closed, shallowly immutable model with deterministic serialisation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    def stable_json_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def stable_json(self) -> str:
        return self.stable_json_bytes().decode("utf-8")

    def content_digest(self) -> str:
        return sha256_digest(self.stable_json_bytes())


class V2Contract(StrictModel):
    schema_version: Literal["v2"] = SCHEMA_VERSION


class ArtifactRef(V2Contract):
    """Immutable reference to one logical artifact revision and its content."""

    artifact_id: Identifier
    revision_id: ContentHash
    artifact_type: Identifier
    content_hash: ContentHash
    media_type: NonEmptyStr
    size_bytes: Annotated[int, Field(ge=0)]


class KeyValue(V2Contract):
    """Auditable, JSON-safe parameter without accepting arbitrary model fields."""

    key: Identifier
    value: JsonValue


__all__ = [
    "ArtifactRef",
    "ContentHash",
    "Identifier",
    "JsonObject",
    "KeyValue",
    "NonEmptyStr",
    "SCHEMA_VERSION",
    "StrictModel",
    "V2Contract",
    "canonical_json_bytes",
    "sha256_digest",
]

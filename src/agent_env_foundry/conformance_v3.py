"""Host-owned environment conformance receipt for EnvironmentRelease/3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_env_foundry.environment import JSONObject, ToolSpec, validate_tool_catalog
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.release import (
    _entrypoint_reference,
    _hex_digest,
    canonical_bytes,
    sha256_hex,
)
from agent_env_foundry.schema import require_object_root, validate_schema_document

CONFORMANCE_FORMAT_V3 = "environment-conformance/3"
_RECEIPT_KEYS = frozenset(
    {
        "format",
        "verdict",
        "actor_project_digest",
        "actor_factory",
        "state_reader_factory",
        "start_schema_digest",
        "reset_observation_schema_digest",
        "state_schema_digest",
        "tool_catalog_digest",
        "evidence_digest",
    }
)


class ConformanceContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EnvironmentConformanceReceipt:
    format: str
    verdict: str
    actor_project_digest: str
    actor_factory: str
    state_reader_factory: str
    start_schema_digest: str
    reset_observation_schema_digest: str
    state_schema_digest: str
    tool_catalog_digest: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if self.format != CONFORMANCE_FORMAT_V3:
            raise ConformanceContractError("conformance format must be environment-conformance/3")
        if self.verdict != "passed":
            raise ConformanceContractError("conformance verdict must be passed")
        for name in (
            "actor_project_digest",
            "start_schema_digest",
            "reset_observation_schema_digest",
            "state_schema_digest",
            "tool_catalog_digest",
            "evidence_digest",
        ):
            try:
                _hex_digest(getattr(self, name), field=name)
            except Exception as exc:
                raise ConformanceContractError(str(exc)) from exc
        try:
            _entrypoint_reference(self.actor_factory, "actor_factory")
            _entrypoint_reference(self.state_reader_factory, "state_reader_factory")
        except Exception as exc:
            raise ConformanceContractError(str(exc)) from exc

    @property
    def receipt_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "verdict": self.verdict,
            "actor_project_digest": self.actor_project_digest,
            "actor_factory": self.actor_factory,
            "state_reader_factory": self.state_reader_factory,
            "start_schema_digest": self.start_schema_digest,
            "reset_observation_schema_digest": self.reset_observation_schema_digest,
            "state_schema_digest": self.state_schema_digest,
            "tool_catalog_digest": self.tool_catalog_digest,
            "evidence_digest": self.evidence_digest,
        }


def make_conformance_receipt(
    *,
    actor_project_digest: str,
    actor_factory: str,
    state_reader_factory: str,
    start_schema: JSONObject,
    reset_observation_schema: JSONObject,
    state_schema: JSONObject,
    tool_specs: tuple[ToolSpec, ...],
    evidence: JSONObject,
) -> EnvironmentConformanceReceipt:
    try:
        require_object_root(start_schema, role="v3 start schema")
        validate_schema_document(reset_observation_schema, role="v3 reset schema")
        validate_schema_document(state_schema, role="v3 state schema")
        catalog = tuple(validate_tool_catalog(tool_specs, role="v3 conformance tools").values())
    except Exception as exc:
        raise ConformanceContractError(str(exc)) from exc
    if not is_json_object(evidence):
        raise ConformanceContractError("conformance evidence must be a JSON object")
    return EnvironmentConformanceReceipt(
        CONFORMANCE_FORMAT_V3,
        "passed",
        actor_project_digest,
        actor_factory,
        state_reader_factory,
        sha256_hex(canonical_bytes(start_schema)),
        sha256_hex(canonical_bytes(reset_observation_schema)),
        sha256_hex(canonical_bytes(state_schema)),
        sha256_hex(canonical_bytes({"tools": [dict(item) for item in catalog]})),
        sha256_hex(canonical_bytes(evidence)),
    )


def conformance_receipt_from_document(document: Any) -> EnvironmentConformanceReceipt:
    if not is_json_object(document) or set(document) != _RECEIPT_KEYS:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ConformanceContractError(
            f"conformance receipt must contain exactly {sorted(_RECEIPT_KEYS)}, got {actual}"
        )
    return EnvironmentConformanceReceipt(
        format=document["format"],
        verdict=document["verdict"],
        actor_project_digest=document["actor_project_digest"],
        actor_factory=document["actor_factory"],
        state_reader_factory=document["state_reader_factory"],
        start_schema_digest=document["start_schema_digest"],
        reset_observation_schema_digest=document["reset_observation_schema_digest"],
        state_schema_digest=document["state_schema_digest"],
        tool_catalog_digest=document["tool_catalog_digest"],
        evidence_digest=document["evidence_digest"],
    )


__all__ = [
    "CONFORMANCE_FORMAT_V3",
    "ConformanceContractError",
    "EnvironmentConformanceReceipt",
    "conformance_receipt_from_document",
    "make_conformance_receipt",
]

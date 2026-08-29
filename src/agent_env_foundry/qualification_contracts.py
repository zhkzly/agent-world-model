"""Immutable contracts for v2 Qualification and release sealing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec, validate_tool_catalog
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.schema import require_object_root, validate_schema_document
from agent_env_foundry.semantics import (
    CapabilitySpec,
    StartCase,
    TraceEvent,
    capability_from_document,
    start_case_from_document,
    trace_event_from_document,
    validate_catalog,
    validate_start_cases,
)

RequirementDisposition = Literal["Taskable", "NotTaskable", "Unsupported"]
_DISPOSITIONS = frozenset({"Taskable", "NotTaskable", "Unsupported"})
_HEX = frozenset("0123456789abcdef")


class QualificationContractError(ValueError):
    """A v2 Qualification identity or sealed document is invalid."""


def _document_digest(document: Any) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicSurfaceManifest:
    start_schema: JSONObject
    reset_observation_schema: JSONObject
    tool_specs: tuple[ToolSpec, ...]
    public_documents_digest: str

    def __post_init__(self) -> None:
        _digest(self.public_documents_digest, "public_documents_digest")
        try:
            require_object_root(self.start_schema, role="public start schema")
            validate_schema_document(
                self.reset_observation_schema,
                role="public reset observation schema",
            )
            validate_tool_catalog(self.tool_specs, role="sealed public ToolSpecs")
        except Exception as exc:
            raise QualificationContractError(str(exc)) from exc

    @property
    def tool_catalog_digest(self) -> str:
        return _document_digest({"tool_specs": [dict(item) for item in self.tool_specs]})

    @property
    def manifest_digest(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "public-surface/2",
            "start_schema": _json(self.start_schema),
            "reset_observation_schema": _json(self.reset_observation_schema),
            "tool_specs": [_json(dict(item)) for item in self.tool_specs],
            "public_documents_digest": self.public_documents_digest,
            "tool_catalog_digest": self.tool_catalog_digest,
        }


@dataclass(frozen=True, slots=True)
class QualifiedCatalogManifest:
    capabilities: tuple[CapabilitySpec, ...]

    def __post_init__(self) -> None:
        if not self.capabilities:
            raise QualificationContractError("qualified catalog must not be empty")
        try:
            validate_catalog(self.capabilities)
        except Exception as exc:
            raise QualificationContractError(str(exc)) from exc

    @property
    def catalog_digest(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "qualified-catalog/2",
            "capabilities": [item.to_document() for item in self.capabilities],
        }


@dataclass(frozen=True, slots=True)
class RequirementCoverageEntry:
    requirement_id: str
    disposition: RequirementDisposition
    capability_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.requirement_id, "requirement_id")
        if self.disposition not in _DISPOSITIONS:
            raise QualificationContractError("requirement disposition is invalid")
        _identifiers(self.capability_ids, "capability_ids")
        _identifiers(self.evidence_ids, "evidence_ids")
        if not self.evidence_ids:
            raise QualificationContractError("requirement coverage requires evidence_ids")
        if self.disposition == "Taskable" and not self.capability_ids:
            raise QualificationContractError("Taskable requirement requires capability_ids")
        if self.disposition != "Taskable" and self.capability_ids:
            raise QualificationContractError(
                "non-Taskable requirement must not declare capability_ids"
            )

    def to_document(self) -> JSONObject:
        return {
            "requirement_id": self.requirement_id,
            "disposition": self.disposition,
            "capability_ids": list(self.capability_ids),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class RequirementCoverageManifest:
    entries: tuple[RequirementCoverageEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise QualificationContractError("requirement coverage must not be empty")
        _unique(tuple(item.requirement_id for item in self.entries), "requirement IDs")

    @property
    def coverage_digest(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "requirement-coverage/2",
            "entries": [item.to_document() for item in self.entries],
        }


@dataclass(frozen=True, slots=True)
class QualifiedStartCasesManifest:
    seed: int
    requested_limit: int
    cases: tuple[StartCase, ...]

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise QualificationContractError("qualified StartCase seed must be integer")
        if self.requested_limit <= 0:
            raise QualificationContractError("qualified StartCase limit must be positive")
        if not self.cases:
            raise QualificationContractError("qualified StartCases must not be empty")
        if len(self.cases) > self.requested_limit:
            raise QualificationContractError("qualified StartCases exceed requested_limit")
        _unique(tuple(item.case_id for item in self.cases), "qualified StartCase IDs")

    def validate_against(self, surface: PublicSurfaceManifest) -> None:
        try:
            validate_start_cases(
                self.cases,
                start_schema=surface.start_schema,
                limit=self.requested_limit,
            )
        except Exception as exc:
            raise QualificationContractError(str(exc)) from exc

    @property
    def start_cases_digest(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "qualified-start-cases/2",
            "seed": self.seed,
            "requested_limit": self.requested_limit,
            "cases": [item.to_document() for item in self.cases],
        }


@dataclass(frozen=True, slots=True)
class QualificationCore:
    expected_semantics_digest: str
    actor_project_digest: str
    actor_factory: str
    semantics_project_digest: str
    semantics_factory: str
    verifier_project_digest: str
    verifier_factory: str
    public_surface_manifest_digest: str

    def __post_init__(self) -> None:
        for value, role in (
            (self.expected_semantics_digest, "expected_semantics_digest"),
            (self.actor_project_digest, "actor_project_digest"),
            (self.semantics_project_digest, "semantics_project_digest"),
            (self.verifier_project_digest, "verifier_project_digest"),
            (self.public_surface_manifest_digest, "public_surface_manifest_digest"),
        ):
            _digest(value, role)
        for factory_value, role in (
            (self.actor_factory, "actor_factory"),
            (self.semantics_factory, "semantics_factory"),
            (self.verifier_factory, "verifier_factory"),
        ):
            _factory(factory_value, role)
        if self.verifier_factory != ("generated_qualification_verifier.release:make_verifier"):
            raise QualificationContractError(
                "verifier_factory must use the fixed Qualification Verifier factory"
            )

    @property
    def core_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "qualification-core/2",
            "expected_semantics_digest": self.expected_semantics_digest,
            "actor_project_digest": self.actor_project_digest,
            "actor_factory": self.actor_factory,
            "semantics_project_digest": self.semantics_project_digest,
            "semantics_factory": self.semantics_factory,
            "verifier_project_digest": self.verifier_project_digest,
            "verifier_factory": self.verifier_factory,
            "public_surface_manifest_digest": self.public_surface_manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class NativeVerificationRequest:
    capability_id: str
    start_case_id: str
    public_descriptor: JSONObject
    public_trace: tuple[TraceEvent, ...]
    final_answer: JSONValue | None
    before_instance_directory: Path
    after_instance_directory: Path

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "native capability_id")
        _identifier(self.start_case_id, "native start_case_id")
        if not is_json_object(self.public_descriptor):
            raise QualificationContractError("native public_descriptor must be an object")
        if not is_json_value(self.final_answer):
            raise QualificationContractError("native final_answer must be JSON")
        _unique(tuple(item.seq for item in self.public_trace), "native trace sequence numbers")
        if self.before_instance_directory == self.after_instance_directory:
            raise QualificationContractError(
                "native before/after instance directories must be distinct"
            )

    def to_document(self) -> JSONObject:
        return {
            "capability_id": self.capability_id,
            "start_case_id": self.start_case_id,
            "public_descriptor": _json(self.public_descriptor),
            "public_trace": [item.to_document() for item in self.public_trace],
            "final_answer": _json(self.final_answer),
            "before_instance_directory": str(self.before_instance_directory),
            "after_instance_directory": str(self.after_instance_directory),
        }


@dataclass(frozen=True, slots=True)
class NativeVerificationResult:
    initially_satisfied: bool
    satisfied: bool
    required_effects_ok: bool
    collateral_ok: bool
    answer_ok: bool | None
    process_ok: bool | None
    report_values: JSONObject
    failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for boolean_value, role in (
            (self.initially_satisfied, "initially_satisfied"),
            (self.satisfied, "satisfied"),
            (self.required_effects_ok, "required_effects_ok"),
            (self.collateral_ok, "collateral_ok"),
        ):
            if not isinstance(boolean_value, bool):
                raise QualificationContractError(f"native {role} must be boolean")
        for optional_value, role in (
            (self.answer_ok, "answer_ok"),
            (self.process_ok, "process_ok"),
        ):
            if optional_value is not None and not isinstance(optional_value, bool):
                raise QualificationContractError(f"native {role} must be boolean or null")
        if not is_json_object(self.report_values):
            raise QualificationContractError("native report_values must be an object")
        _identifiers(self.failure_codes, "native failure_codes")
        if self.satisfied and (
            not self.required_effects_ok
            or not self.collateral_ok
            or self.answer_ok is False
            or self.process_ok is False
            or self.failure_codes
        ):
            raise QualificationContractError("satisfied native result is contradictory")

    def to_document(self) -> JSONObject:
        return {
            "initially_satisfied": self.initially_satisfied,
            "satisfied": self.satisfied,
            "required_effects_ok": self.required_effects_ok,
            "collateral_ok": self.collateral_ok,
            "answer_ok": self.answer_ok,
            "process_ok": self.process_ok,
            "report_values": _json(self.report_values),
            "failure_codes": list(self.failure_codes),
        }


@dataclass(frozen=True, slots=True)
class QualificationReceipt:
    core_id: str
    expected_semantics_digest: str
    actor_project_digest: str
    semantics_project_digest: str
    verifier_project_digest: str
    public_surface_manifest_digest: str
    qualified_catalog_digest: str
    requirement_coverage_digest: str
    qualified_start_cases_digest: str
    evidence_manifest_digest: str

    def __post_init__(self) -> None:
        for name in (
            "core_id",
            "expected_semantics_digest",
            "actor_project_digest",
            "semantics_project_digest",
            "verifier_project_digest",
            "public_surface_manifest_digest",
            "qualified_catalog_digest",
            "requirement_coverage_digest",
            "qualified_start_cases_digest",
            "evidence_manifest_digest",
        ):
            _digest(getattr(self, name), name)

    @property
    def receipt_digest(self) -> str:
        return _document_digest(self.to_document())

    def validate_core(self, core: QualificationCore) -> None:
        expected = {
            "core_id": core.core_id,
            "expected_semantics_digest": core.expected_semantics_digest,
            "actor_project_digest": core.actor_project_digest,
            "semantics_project_digest": core.semantics_project_digest,
            "verifier_project_digest": core.verifier_project_digest,
            "public_surface_manifest_digest": core.public_surface_manifest_digest,
        }
        actual = {name: getattr(self, name) for name in expected}
        if actual != expected:
            raise QualificationContractError("Qualification receipt does not bind its Core")

    def to_document(self) -> JSONObject:
        return {
            "format": "environment-qualification/2",
            "verdict": "passed",
            "core_id": self.core_id,
            "expected_semantics_digest": self.expected_semantics_digest,
            "actor_project_digest": self.actor_project_digest,
            "semantics_project_digest": self.semantics_project_digest,
            "verifier_project_digest": self.verifier_project_digest,
            "public_surface_manifest_digest": self.public_surface_manifest_digest,
            "qualified_catalog_digest": self.qualified_catalog_digest,
            "requirement_coverage_digest": self.requirement_coverage_digest,
            "qualified_start_cases_digest": self.qualified_start_cases_digest,
            "evidence_manifest_digest": self.evidence_manifest_digest,
        }


def public_surface_manifest_from_document(value: Any) -> PublicSurfaceManifest:
    document = _exact(
        value,
        {
            "format",
            "start_schema",
            "reset_observation_schema",
            "tool_specs",
            "public_documents_digest",
            "tool_catalog_digest",
        },
        "PublicSurfaceManifest",
    )
    if document["format"] != "public-surface/2":
        raise QualificationContractError("PublicSurfaceManifest format is invalid")
    raw_specs = _array(document["tool_specs"], "tool_specs")
    specs: list[ToolSpec] = []
    for position, item in enumerate(raw_specs):
        if not is_json_object(item):
            raise QualificationContractError(f"tool_specs[{position}] must be an object")
        specs.append(cast(ToolSpec, item))
    manifest = PublicSurfaceManifest(
        _object(document["start_schema"], "start_schema"),
        _object(document["reset_observation_schema"], "reset_observation_schema"),
        tuple(specs),
        _string(document["public_documents_digest"], "public_documents_digest"),
    )
    if document["tool_catalog_digest"] != manifest.tool_catalog_digest:
        raise QualificationContractError("PublicSurfaceManifest tool catalog digest mismatch")
    return manifest


def qualified_catalog_manifest_from_document(value: Any) -> QualifiedCatalogManifest:
    document = _exact(
        value,
        {"format", "capabilities"},
        "QualifiedCatalogManifest",
    )
    if document["format"] != "qualified-catalog/2":
        raise QualificationContractError("QualifiedCatalogManifest format is invalid")
    return QualifiedCatalogManifest(
        tuple(
            capability_from_document(item)
            for item in _array(document["capabilities"], "capabilities")
        )
    )


def requirement_coverage_manifest_from_document(value: Any) -> RequirementCoverageManifest:
    document = _exact(
        value,
        {"format", "entries"},
        "RequirementCoverageManifest",
    )
    if document["format"] != "requirement-coverage/2":
        raise QualificationContractError("RequirementCoverageManifest format is invalid")
    entries: list[RequirementCoverageEntry] = []
    for position, raw in enumerate(_array(document["entries"], "entries")):
        item = _exact(
            raw,
            {"requirement_id", "disposition", "capability_ids", "evidence_ids"},
            f"RequirementCoverageEntry[{position}]",
        )
        entries.append(
            RequirementCoverageEntry(
                _string(item["requirement_id"], "requirement_id"),
                cast(
                    RequirementDisposition,
                    _string(item["disposition"], "disposition"),
                ),
                _string_tuple(item["capability_ids"], "capability_ids"),
                _string_tuple(item["evidence_ids"], "evidence_ids"),
            )
        )
    return RequirementCoverageManifest(tuple(entries))


def qualified_start_cases_manifest_from_document(value: Any) -> QualifiedStartCasesManifest:
    document = _exact(
        value,
        {"format", "seed", "requested_limit", "cases"},
        "QualifiedStartCasesManifest",
    )
    if document["format"] != "qualified-start-cases/2":
        raise QualificationContractError("QualifiedStartCasesManifest format is invalid")
    seed = _integer(document["seed"], "seed")
    limit = _integer(document["requested_limit"], "requested_limit")
    return QualifiedStartCasesManifest(
        seed,
        limit,
        tuple(start_case_from_document(item) for item in _array(document["cases"], "cases")),
    )


def qualification_core_from_document(value: Any) -> QualificationCore:
    keys = {
        "format",
        "expected_semantics_digest",
        "actor_project_digest",
        "actor_factory",
        "semantics_project_digest",
        "semantics_factory",
        "verifier_project_digest",
        "verifier_factory",
        "public_surface_manifest_digest",
    }
    document = _exact(value, keys, "QualificationCore")
    if document["format"] != "qualification-core/2":
        raise QualificationContractError("QualificationCore format is invalid")
    return QualificationCore(
        expected_semantics_digest=_string(
            document["expected_semantics_digest"], "expected_semantics_digest"
        ),
        actor_project_digest=_string(document["actor_project_digest"], "actor_project_digest"),
        actor_factory=_string(document["actor_factory"], "actor_factory"),
        semantics_project_digest=_string(
            document["semantics_project_digest"], "semantics_project_digest"
        ),
        semantics_factory=_string(document["semantics_factory"], "semantics_factory"),
        verifier_project_digest=_string(
            document["verifier_project_digest"], "verifier_project_digest"
        ),
        verifier_factory=_string(document["verifier_factory"], "verifier_factory"),
        public_surface_manifest_digest=_string(
            document["public_surface_manifest_digest"],
            "public_surface_manifest_digest",
        ),
    )


def native_verification_request_from_document(value: Any) -> NativeVerificationRequest:
    document = _exact(
        value,
        {
            "capability_id",
            "start_case_id",
            "public_descriptor",
            "public_trace",
            "final_answer",
            "before_instance_directory",
            "after_instance_directory",
        },
        "NativeVerificationRequest",
    )
    final_answer = document["final_answer"]
    if not is_json_value(final_answer):
        raise QualificationContractError("final_answer must be JSON")
    return NativeVerificationRequest(
        _string(document["capability_id"], "capability_id"),
        _string(document["start_case_id"], "start_case_id"),
        _object(document["public_descriptor"], "public_descriptor"),
        tuple(
            trace_event_from_document(item)
            for item in _array(document["public_trace"], "public_trace")
        ),
        cast(JSONValue | None, final_answer),
        Path(_string(document["before_instance_directory"], "before_instance_directory")),
        Path(_string(document["after_instance_directory"], "after_instance_directory")),
    )


def native_verification_result_from_document(value: Any) -> NativeVerificationResult:
    document = _exact(
        value,
        {
            "initially_satisfied",
            "satisfied",
            "required_effects_ok",
            "collateral_ok",
            "answer_ok",
            "process_ok",
            "report_values",
            "failure_codes",
        },
        "NativeVerificationResult",
    )
    return NativeVerificationResult(
        _boolean(document["initially_satisfied"], "initially_satisfied"),
        _boolean(document["satisfied"], "satisfied"),
        _boolean(document["required_effects_ok"], "required_effects_ok"),
        _boolean(document["collateral_ok"], "collateral_ok"),
        _optional_boolean(document["answer_ok"], "answer_ok"),
        _optional_boolean(document["process_ok"], "process_ok"),
        _object(document["report_values"], "report_values"),
        _string_tuple(document["failure_codes"], "failure_codes"),
    )


def qualification_receipt_from_document(value: Any) -> QualificationReceipt:
    keys = {
        "format",
        "verdict",
        "core_id",
        "expected_semantics_digest",
        "actor_project_digest",
        "semantics_project_digest",
        "verifier_project_digest",
        "public_surface_manifest_digest",
        "qualified_catalog_digest",
        "requirement_coverage_digest",
        "qualified_start_cases_digest",
        "evidence_manifest_digest",
    }
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise QualificationContractError(
            f"Qualification receipt must have exactly {sorted(keys)}, got {actual}"
        )
    if value["format"] != "environment-qualification/2":
        raise QualificationContractError("Qualification receipt format is invalid")
    if value["verdict"] != "passed":
        raise QualificationContractError("Qualification receipt verdict must be passed")
    return QualificationReceipt(
        core_id=_string(value["core_id"], "core_id"),
        expected_semantics_digest=_string(
            value["expected_semantics_digest"], "expected_semantics_digest"
        ),
        actor_project_digest=_string(value["actor_project_digest"], "actor_project_digest"),
        semantics_project_digest=_string(
            value["semantics_project_digest"], "semantics_project_digest"
        ),
        verifier_project_digest=_string(
            value["verifier_project_digest"], "verifier_project_digest"
        ),
        public_surface_manifest_digest=_string(
            value["public_surface_manifest_digest"], "public_surface_manifest_digest"
        ),
        qualified_catalog_digest=_string(
            value["qualified_catalog_digest"], "qualified_catalog_digest"
        ),
        requirement_coverage_digest=_string(
            value["requirement_coverage_digest"], "requirement_coverage_digest"
        ),
        qualified_start_cases_digest=_string(
            value["qualified_start_cases_digest"], "qualified_start_cases_digest"
        ),
        evidence_manifest_digest=_string(
            value["evidence_manifest_digest"], "evidence_manifest_digest"
        ),
    )


def _exact(value: Any, keys: set[str], role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise QualificationContractError(f"{role} must have exactly {sorted(keys)}, got {actual}")
    return cast(dict[str, Any], value)


def _array(value: Any, role: str) -> list[Any]:
    if not isinstance(value, list):
        raise QualificationContractError(f"{role} must be an array")
    return value


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise QualificationContractError(f"{role} must be a JSON object")
    return cast(JSONObject, value)


def _string_tuple(value: Any, role: str) -> tuple[str, ...]:
    values = _array(value, role)
    if any(not isinstance(item, str) for item in values):
        raise QualificationContractError(f"{role} must contain only strings")
    return tuple(cast(list[str], values))


def _integer(value: Any, role: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise QualificationContractError(f"{role} must be integer")
    return value


def _boolean(value: Any, role: str) -> bool:
    if not isinstance(value, bool):
        raise QualificationContractError(f"{role} must be boolean")
    return value


def _optional_boolean(value: Any, role: str) -> bool | None:
    return None if value is None else _boolean(value, role)


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise QualificationContractError(f"{role} must be a lowercase SHA-256 digest")


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise QualificationContractError(f"{role} must be a non-empty whitespace-free string")


def _identifiers(values: tuple[str, ...], role: str) -> None:
    for value in values:
        _identifier(value, role)
    _unique(values, role)


def _unique(values: tuple[Any, ...], role: str) -> None:
    if len(values) != len(set(values)):
        raise QualificationContractError(f"{role} must be unique")


def _factory(value: str, role: str) -> None:
    if value.count(":") != 1:
        raise QualificationContractError(f"{role} must be a module:factory reference")
    module, _, attribute = value.partition(":")
    if not module or not attribute or any(character.isspace() for character in value):
        raise QualificationContractError(f"{role} must be a module:factory reference")


def _string(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise QualificationContractError(f"{role} must be a string")
    return value


def _json(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        if not is_json_value(value):
            raise QualificationContractError("non-finite JSON number")
        return value
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise QualificationContractError("JSON object keys must be strings")
        return {key: _json(item) for key, item in value.items()}
    if hasattr(value, "to_document"):
        return _json(value.to_document())
    raise QualificationContractError(f"not JSON-compatible: {type(value).__name__}")


__all__ = [
    "NativeVerificationRequest",
    "NativeVerificationResult",
    "PublicSurfaceManifest",
    "QualificationContractError",
    "QualificationCore",
    "QualificationReceipt",
    "QualifiedCatalogManifest",
    "QualifiedStartCasesManifest",
    "RequirementCoverageEntry",
    "RequirementCoverageManifest",
    "native_verification_request_from_document",
    "native_verification_result_from_document",
    "public_surface_manifest_from_document",
    "qualification_core_from_document",
    "qualification_receipt_from_document",
    "qualified_catalog_manifest_from_document",
    "qualified_start_cases_manifest_from_document",
    "requirement_coverage_manifest_from_document",
]

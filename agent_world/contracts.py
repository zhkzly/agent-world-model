"""Small, framework-owned contracts for the Direct-only Foundry path.

These contracts deliberately model only facts the framework may persist.  Raw
prompts, provider payloads, credentials, sealed cases, and candidate claims do
not belong here.
"""

from __future__ import annotations

import json
import re
import typing
from dataclasses import asdict, dataclass, field, is_dataclass
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from hashlib import sha256
from types import UnionType
from typing import Any, Literal
from uuid import uuid4

TerminalStatus = Literal[
    "running",
    "released",
    "rejected",
    "needs_human",
    "budget_exhausted",
    "error",
]
GateStatus = Literal["passed", "failed", "not_run"]
GraphId = Literal["design", "candidate"]
NodeOwner = Literal["controller", "designer", "builder", "judge", "registry"]
ExecutionKind = Literal["framework", "direct_llm", "agent", "candidate_process"]
WorkStatus = Literal["passed", "failed", "inconclusive", "error", "not_run"]
OperationCategory = Literal["direct_llm", "agent", "search", "fetch", "extract"]
VerifierFamily = Literal[
    "unknown_seed",
    "alternate_difficulty",
    "idempotency_key_variation",
    "argument_variation",
]
ExpectedOutputCategory = Literal[
    "object",
    "array",
    "string",
    "number",
    "boolean",
    "semantic_draft",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def digest_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def json_value(value: Any) -> Any:
    """Turn known framework dataclasses into JSON-ready values."""

    if is_dataclass(value) and not isinstance(value, type):
        return {key: json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def digest_value(value: Any) -> str:
    """Return the canonical digest used by frozen framework contracts."""

    return digest_text(
        json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def from_value(value: Any, type_hint: Any) -> Any:
    """Inverse of *json_value*: reconstruct a typed value from JSON-ready data.

    Type-hint driven: dataclasses are rebuilt (re-running ``__post_init__``),
    JSON lists become tuples when the hint says *tuple*, and ``Optional``/
    ``X | None`` are unwrapped.  Basic types pass through unchanged.
    """

    origin = typing.get_origin(type_hint)

    # Union / Optional / X | None ---------------------------------------------------
    if origin is typing.Union or origin is UnionType:
        args = typing.get_args(type_hint)
        if len(args) == 2 and type(None) in args:
            if value is None:
                return None
            non_none = next(a for a in args if a is not type(None))
            return from_value(value, non_none)
        return value

    # Literal -----------------------------------------------------------------------
    if origin is typing.Literal:
        return value

    # tuple -------------------------------------------------------------------------
    if origin is tuple:
        args = typing.get_args(type_hint)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_value(item, args[0]) for item in value)
        return tuple(from_value(item, arg) for item, arg in zip(value, args, strict=True))

    # list --------------------------------------------------------------------------
    if origin is list:
        args = typing.get_args(type_hint)
        if args:
            return [from_value(item, args[0]) for item in value]
        return list(value)

    # dict ---------------------------------------------------------------------------
    if origin is dict:
        args = typing.get_args(type_hint)
        if len(args) == 2:
            return {k: from_value(v, args[1]) for k, v in value.items()}
        return dict(value)

    # dataclass ----------------------------------------------------------------------
    if isinstance(type_hint, type) and is_dataclass(type_hint):
        hints = typing.get_type_hints(type_hint)
        field_names = {f.name for f in dataclass_fields(type_hint)}
        kwargs = {
            name: from_value(value[name], hints.get(name, Any))
            for name in field_names
            if name in value
        }
        return type_hint(**kwargs)

    # basic types (str, int, float, bool, None, Any) --------------------------------
    return value


def _digest(value: str, code: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(code)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    digest: str
    path: str
    media_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class CorrectionPacket:
    """One safe, framework-built local model-output correction instruction."""

    code: str
    path: str
    violated_condition: str
    expected_category: ExpectedOutputCategory

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.code)
            or not re.fullmatch(r"\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*", self.path)
            or not self.violated_condition.strip()
            or len(self.violated_condition) > 280
        ):
            raise ValueError("correction_packet_invalid")


@dataclass(frozen=True, slots=True)
class OperationEvidence:
    """Secret-safe fact about one real model or research-tool operation."""

    category: OperationCategory
    node_id: str
    model: str | None
    usage: dict[str, int] | None
    skill_digest: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.node_id):
            raise ValueError("operation_evidence_node_invalid")
        if self.category in {"direct_llm", "agent"} and not self.model:
            raise ValueError("operation_evidence_model_required")
        if self.category == "agent" and (
            self.skill_digest is None or not self.skill_digest.startswith("sha256:")
        ):
            raise ValueError("operation_evidence_skill_required")
        if self.category != "agent" and self.skill_digest is not None:
            raise ValueError("operation_evidence_skill_forbidden")
        if self.usage is not None and (
            not self.usage
            or any(
                key
                not in {
                    "total_tokens",
                    "cached_input_tokens",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                }
                or type(value) is not int
                or value < 0
                for key, value in self.usage.items()
            )
        ):
            raise ValueError("operation_evidence_usage_invalid")


@dataclass(frozen=True, slots=True)
class WorkCoordinate:
    """Stable, graph-local identity for one immutable Direct work revision."""

    run_id: str
    graph_id: GraphId
    node_id: str
    shard_key: str | None
    revision: int

    def __post_init__(self) -> None:
        if not self.run_id or not self.node_id or self.revision < 1:
            raise ValueError("work_coordinate_invalid")


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    """Framework-only provenance wrapped around a graph output payload."""

    kind: str
    schema_version: int
    producer: WorkCoordinate
    semantic_revision_digest: str
    dependencies: tuple[ArtifactRef, ...]
    output_ports: tuple[str, ...]
    payload: Any

    def __post_init__(self) -> None:
        if self.schema_version < 1 or not self.semantic_revision_digest.startswith("sha256:"):
            raise ValueError("artifact_envelope_invalid")
        if len({ref.artifact_id for ref in self.dependencies}) != len(self.dependencies):
            raise ValueError("artifact_dependency_duplicate")
        if (
            not self.output_ports
            or len(set(self.output_ports)) != len(self.output_ports)
            or any(not isinstance(port, str) or not port for port in self.output_ports)
        ):
            raise ValueError("artifact_output_ports_invalid")


@dataclass(frozen=True, slots=True)
class WorkRecord:
    coordinate: WorkCoordinate
    owner: NodeOwner
    execution_kind: ExecutionKind
    semantic_revision_digest: str
    input_refs: tuple[ArtifactRef, ...]
    dependency_refs: tuple[ArtifactRef, ...]
    output_refs: tuple[ArtifactRef, ...]
    validation_ref: ArtifactRef | None
    assurance_refs: tuple[ArtifactRef, ...]
    finding_refs: tuple[ArtifactRef, ...]
    status: WorkStatus
    safe_code: str | None = None
    invalidated_by: None = None

    def __post_init__(self) -> None:
        if not self.semantic_revision_digest.startswith("sha256:"):
            raise ValueError("work_semantic_revision_invalid")
        if self.invalidated_by is not None:
            raise ValueError("direct_work_invalidation_forbidden")
        if self.status == "passed" and (not self.output_refs or self.validation_ref is None):
            raise ValueError("passed_work_evidence_required")
        if self.status == "not_run" and (
            self.output_refs or self.validation_ref or self.assurance_refs or self.finding_refs
        ):
            raise ValueError("not_run_work_must_be_empty")
        if self.status in {"failed", "inconclusive"} and (
            self.validation_ref is None or not self.finding_refs
        ):
            raise ValueError("failed_work_evidence_required")


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    failed_claim_ref: ArtifactRef
    subject_ref: ArtifactRef
    evidence_refs: tuple[ArtifactRef, ...]
    expected_condition: str
    owner: NodeOwner
    code: str
    category: str
    severity: Literal["block_revision", "block_integration", "block_release"]
    blocks_release: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if (
            not self.evidence_refs
            or not self.blocks_release
            or not self.fingerprint.startswith("sha256:")
        ):
            raise ValueError("finding_invalid")


@dataclass(frozen=True, slots=True)
class DifficultyLevel:
    name: str
    meaning: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", self.name):
            raise ValueError("difficulty_level_name_invalid")
        if not self.meaning.strip() or len(self.meaning) > 300:
            raise ValueError("difficulty_level_meaning_invalid")


@dataclass(frozen=True, slots=True)
class DifficultyDimension:
    name: str
    meaning: str
    levels: tuple[DifficultyLevel, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", self.name):
            raise ValueError("difficulty_dimension_name_invalid")
        if not self.meaning.strip() or len(self.meaning) > 300:
            raise ValueError("difficulty_dimension_meaning_invalid")


@dataclass(frozen=True, slots=True)
class DifficultySchema:
    task_family_id: str
    dimensions: tuple[DifficultyDimension, ...]
    key_order: tuple[str, ...]
    schema_digest: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.dimensions) <= 6 or self.key_order != tuple(
            dimension.name for dimension in self.dimensions
        ):
            raise ValueError("difficulty_schema_invalid")
        if not self.schema_digest.startswith("sha256:"):
            raise ValueError("difficulty_schema_digest_invalid")
        if len(set(self.key_order)) != len(self.key_order):
            raise ValueError("difficulty_dimension_duplicate")
        for dimension in self.dimensions:
            if not 2 <= len(dimension.levels) <= 5 or len(
                {level.name for level in dimension.levels}
            ) != len(dimension.levels):
                raise ValueError("difficulty_level_invalid")


def compile_difficulty_schema(
    task_family_id: str, dimensions: tuple[DifficultyDimension, ...]
) -> DifficultySchema:
    payload = {
        "task_family_id": task_family_id,
        "dimensions": [
            {
                "name": dimension.name,
                "meaning": dimension.meaning,
                "levels": [asdict(level) for level in dimension.levels],
            }
            for dimension in dimensions
        ],
    }
    digest = digest_value(payload)
    return DifficultySchema(task_family_id, dimensions, tuple(d.name for d in dimensions), digest)


def validate_difficulty_selection(
    schema: DifficultySchema, pairs: tuple[tuple[str, str], ...]
) -> dict[str, str]:
    """Validate duplicate-aware ordered JSON pairs before candidate execution."""

    if tuple(key for key, _ in pairs) != schema.key_order or len({key for key, _ in pairs}) != len(
        pairs
    ):
        raise ValueError("difficulty_selection_order_invalid")
    values = dict(pairs)
    for dimension in schema.dimensions:
        if values[dimension.name] not in {level.name for level in dimension.levels}:
            raise ValueError("difficulty_selection_level_invalid")
    return values


@dataclass(frozen=True, slots=True)
class RegistryReceipt:
    """Framework-issued publication facts, never a candidate declaration."""

    package_id: str
    version: str
    package_digest: str
    manifest_digest: str
    registry_revision: str
    published_at: str


@dataclass(frozen=True, slots=True)
class EnvironmentPackageRef:
    """Closed released-package handoff emitted only after Registry publication."""

    package_id: str
    version: str
    package_digest: str
    manifest_digest: str
    registry_receipt_ref: ArtifactRef
    design_ref: ArtifactRef
    candidate_manifest_ref: ArtifactRef
    integration_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    semantic_lineage_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef

    def __post_init__(self) -> None:
        if (
            not self.package_id
            or not self.version
            or not self.package_digest.startswith("sha256:")
            or not self.manifest_digest.startswith("sha256:")
        ):
            raise ValueError("environment_package_ref_invalid")


@dataclass(frozen=True, slots=True)
class SafeFailure:
    code: str
    status: TerminalStatus
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class EnvironmentRequest:
    request_id: str
    need: str
    need_digest: str

    @classmethod
    def create(cls, need: str) -> EnvironmentRequest:
        normalized = need.strip()
        if not normalized:
            raise ValueError("request_need_required")
        return cls(
            request_id=new_id("request"), need=normalized, need_digest=digest_text(normalized)
        )


@dataclass(frozen=True, slots=True)
class RunEvent:
    stage: str
    status: str
    at: str
    code: str | None = None
    artifact_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class DirectRun:
    run_id: str
    request_id: str
    request_digest: str
    status: TerminalStatus = "running"
    started_at: str = field(default_factory=utc_now)
    ended_at: str | None = None
    events: list[RunEvent] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    work_records: list[ArtifactRef] = field(default_factory=list)
    release: EnvironmentPackageRef | None = None

    @classmethod
    def create(cls, request: EnvironmentRequest) -> DirectRun:
        return cls(
            run_id=new_id("run"),
            request_id=request.request_id,
            request_digest=request.need_digest,
        )

    def add_event(
        self,
        stage: str,
        status: str,
        *,
        code: str | None = None,
        artifacts: tuple[ArtifactRef, ...] = (),
    ) -> None:
        self.events.append(
            RunEvent(
                stage=stage,
                status=status,
                at=utc_now(),
                code=code,
                artifact_ids=tuple(ref.artifact_id for ref in artifacts),
            )
        )
        for ref in artifacts:
            if ref not in self.artifacts:
                self.artifacts.append(ref)

    def add_work_records(self, refs: tuple[ArtifactRef, ...]) -> None:
        for ref in refs:
            if ref.kind != "control.work_record":
                raise ValueError("run_work_record_invalid")
            if ref not in self.work_records:
                self.work_records.append(ref)

    def finish(
        self,
        status: TerminalStatus,
        *,
        code: str | None = None,
        package_ref: EnvironmentPackageRef | None = None,
    ) -> None:
        if status == "released":
            if package_ref is not None:
                self.release = package_ref
            if self.release is None:
                raise ValueError("released_package_ref_required")
        elif package_ref is not None:
            raise ValueError("non_release_package_ref_forbidden")
        self.status = status
        self.ended_at = utc_now()
        self.add_event("run", status, code=code)

    def to_dict(self) -> dict[str, Any]:
        return json_value(self)


@dataclass(frozen=True, slots=True)
class SemanticBinding:
    """One framework-derived catalog entry available to a closed RuleDraft."""

    index: int
    source: Literal["argument", "tool_result", "pre_state", "post_state"]
    name: str
    path: tuple[str, ...]
    value_category: Literal["json_value"] = "json_value"

    def __post_init__(self) -> None:
        if self.index < 1 or not self.name or not self.path:
            raise ValueError("semantic_binding_invalid")


@dataclass(frozen=True, slots=True)
class PredicateDraft:
    left_semantic_index: int
    operator: Literal[
        "eq", "ne", "lt", "le", "gt", "ge", "contains", "not_contains", "exists", "not_exists"
    ]
    right: Any


@dataclass(frozen=True, slots=True)
class EffectDraft:
    target_semantic_index: int
    operation: Literal["set", "increment", "decrement", "add", "remove", "preserve", "reject"]
    value: Any


@dataclass(frozen=True, slots=True)
class RuleDraft:
    when: tuple[PredicateDraft, ...]
    effects: tuple[EffectDraft, ...]
    error_kind: str | None
    rationale: str
    citation_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FieldDeclaration:
    name: str
    category: Literal[
        "text", "integer", "number", "boolean", "timestamp", "identifier", "enum", "list"
    ]
    required: bool
    values: tuple[str, ...] = ()
    entity_ref: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name):
            raise ValueError("field_name_invalid")
        if (self.category in {"enum", "list"}) != bool(self.values):
            raise ValueError("field_values_invalid")
        if len(set(self.values)) != len(self.values) or any(not value for value in self.values):
            raise ValueError("field_values_invalid")


@dataclass(frozen=True, slots=True)
class CitationCatalogItem:
    index: int
    source_label: str
    source_url: str
    excerpt: str

    def __post_init__(self) -> None:
        if self.index < 1 or not self.source_label or not self.source_url or not self.excerpt:
            raise ValueError("citation_catalog_item_invalid")


@dataclass(frozen=True, slots=True)
class CitationCatalog:
    items: tuple[CitationCatalogItem, ...]

    def __post_init__(self) -> None:
        if tuple(item.index for item in self.items) != tuple(range(1, len(self.items) + 1)):
            raise ValueError("citation_catalog_order_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    statement: str
    kind: Literal["observed", "bounded_inference"]
    citation_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            not self.statement.strip()
            or not self.citation_indexes
            or min(self.citation_indexes) < 1
        ):
            raise ValueError("evidence_claim_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    claims: tuple[EvidenceClaim, ...]
    conflicts: tuple[EvidenceClaim, ...]
    gaps: tuple[str, ...]
    catalog: CitationCatalog
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if not self.claims or len(self.claims) > 32 or any(not gap.strip() for gap in self.gaps):
            raise ValueError("evidence_graph_invalid")
        indexes = {item.index for item in self.catalog.items}
        if any(
            not set(claim.citation_indexes).issubset(indexes)
            for claim in (*self.claims, *self.conflicts)
        ):
            raise ValueError("evidence_citation_reference_invalid")


@dataclass(frozen=True, slots=True)
class WorldBoundary:
    name: str
    purpose: str
    system_of_record: str
    authority: str
    actors: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not all((self.name, self.purpose, self.system_of_record, self.authority))
            or not 1 <= len(self.actors) <= 8
            or len(set(self.actors)) != len(self.actors)
        ):
            raise ValueError("world_boundary_invalid")


@dataclass(frozen=True, slots=True)
class EntityDeclaration:
    name: str
    purpose: str
    fields: tuple[FieldDeclaration, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.purpose or not 1 <= len(self.fields) <= 24:
            raise ValueError("entity_declaration_invalid")
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("entity_field_duplicate")


@dataclass(frozen=True, slots=True)
class ToolSurface:
    tool_index: int
    name: str
    purpose: str
    actor_indexes: tuple[int, ...]
    argument_fields: tuple[FieldDeclaration, ...]
    result_fields: tuple[FieldDeclaration, ...]

    def __post_init__(self) -> None:
        if (
            self.tool_index < 1
            or not self.name
            or not self.purpose
            or not self.actor_indexes
            or len(set(self.actor_indexes)) != len(self.actor_indexes)
            or len({field.name for field in self.argument_fields}) != len(self.argument_fields)
            or len({field.name for field in self.result_fields}) != len(self.result_fields)
        ):
            raise ValueError("tool_surface_invalid")


@dataclass(frozen=True, slots=True)
class SemanticCatalog:
    bindings: tuple[SemanticBinding, ...]

    def __post_init__(self) -> None:
        if tuple(binding.index for binding in self.bindings) != tuple(
            range(1, len(self.bindings) + 1)
        ):
            raise ValueError("semantic_catalog_order_invalid")


@dataclass(frozen=True, slots=True)
class ToolCouplingPlan:
    groups: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        if any(len(group) < 2 or len(set(group)) != len(group) for group in self.groups):
            raise ValueError("tool_coupling_group_invalid")


@dataclass(frozen=True, slots=True)
class WorldArchitecture:
    boundary: WorldBoundary
    entities: tuple[EntityDeclaration, ...]
    tools: tuple[ToolSurface, ...]
    known_divergences: tuple[EvidenceClaim, ...]
    catalog: SemanticCatalog
    coupling_plan: ToolCouplingPlan
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if not 1 <= len(self.entities) <= 16 or not 1 <= len(self.tools) <= 8:
            raise ValueError("world_architecture_cardinality_invalid")
        if tuple(tool.tool_index for tool in self.tools) != tuple(range(1, len(self.tools) + 1)):
            raise ValueError("world_architecture_tool_order_invalid")
        if any(
            actor < 1 or actor > len(self.boundary.actors)
            for tool in self.tools
            for actor in tool.actor_indexes
        ):
            raise ValueError("world_architecture_actor_reference_invalid")
        expected_groups = () if len(self.tools) == 1 else (tuple(range(1, len(self.tools) + 1)),)
        if self.coupling_plan.groups != expected_groups:
            raise ValueError("tool_coupling_plan_invalid")


@dataclass(frozen=True, slots=True)
class SharedToolContract:
    tool_indexes: tuple[int, ...]
    atomicity: tuple[tuple[int, ...], ...]
    concurrency: tuple[tuple[int, ...], ...]
    idempotency: tuple[tuple[int, ...], ...]
    ordering: tuple[str, ...]
    compensation: tuple[str, ...]
    error_policy: tuple[tuple[int, str], ...]
    digest: str
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        members = self.tool_indexes
        if (
            not isinstance(members, tuple)
            or len(members) < 2
            or any(type(member) is not int for member in members)
            or len(set(members)) != len(members)
        ):
            raise ValueError("shared_tool_members_invalid")
        for partition in (self.atomicity, self.concurrency, self.idempotency):
            if (
                not isinstance(partition, tuple)
                or not 1 <= len(partition) <= len(members)
                or any(
                    not isinstance(group, tuple) or not 1 <= len(group) <= len(members)
                    for group in partition
                )
            ):
                raise ValueError("shared_tool_partition_invalid")
            values = tuple(item for group in partition for item in group)
            if (
                any(type(item) is not int or item not in members for item in values)
                or len(values) != len(members)
                or len(set(values)) != len(values)
            ):
                raise ValueError("shared_tool_partition_invalid")
        if (
            not isinstance(self.error_policy, tuple)
            or len(self.error_policy) != len(members)
            or any(not isinstance(item, tuple) or len(item) != 2 for item in self.error_policy)
        ):
            raise ValueError("shared_tool_error_policy_invalid")
        indexes = tuple(item[0] for item in self.error_policy)
        if indexes != members or any(
            type(index) is not int or not isinstance(policy, str) or not policy.strip()
            for index, policy in self.error_policy
        ):
            raise ValueError("shared_tool_error_policy_invalid")
        _digest(self.digest, "shared_tool_digest_invalid")


@dataclass(frozen=True, slots=True)
class ToolDraft:
    tool_index: int
    surface: ToolSurface
    bindings: tuple[SemanticBinding, ...]
    preconditions: tuple[RuleDraft, ...]
    transitions: tuple[RuleDraft, ...]
    postconditions: tuple[RuleDraft, ...]
    errors: tuple[RuleDraft, ...]
    shared_contract_digest: str | None
    local_rules_digest: str

    def __post_init__(self) -> None:
        if self.tool_index != self.surface.tool_index or not self.bindings:
            raise ValueError("tool_draft_invalid")
        _digest(self.local_rules_digest, "tool_draft_digest_invalid")
        if self.shared_contract_digest is not None:
            _digest(self.shared_contract_digest, "tool_draft_shared_digest_invalid")


@dataclass(frozen=True, slots=True)
class WorldRuleSet:
    initial_rules: tuple[RuleDraft, ...]
    invariants: tuple[RuleDraft, ...]
    digest: str
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _digest(self.digest, "world_rule_digest_invalid")


@dataclass(frozen=True, slots=True)
class CurriculumFamily:
    task_family_index: int
    task_family_id: str
    objective: str
    actor_index: int
    tool_indexes: tuple[int, ...]
    difficulty_schema: DifficultySchema
    sampling_intent: str
    citation_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            self.task_family_index < 1
            or not self.task_family_id
            or not self.objective
            or self.actor_index < 1
            or not self.tool_indexes
            or len(set(self.tool_indexes)) != len(self.tool_indexes)
            or self.difficulty_schema.task_family_id != self.task_family_id
        ):
            raise ValueError("curriculum_family_invalid")


@dataclass(frozen=True, slots=True)
class CurriculumPlan:
    families: tuple[CurriculumFamily, ...]
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if not 1 <= len(self.families) <= 8 or tuple(
            family.task_family_index for family in self.families
        ) != tuple(range(1, len(self.families) + 1)):
            raise ValueError("curriculum_plan_order_invalid")


@dataclass(frozen=True, slots=True)
class TaskRequirement:
    task_family_index: int
    public_goal_fields: tuple[int, ...]
    initial_rules: tuple[RuleDraft, ...]
    success_rules: tuple[RuleDraft, ...]
    failure_rules: tuple[RuleDraft, ...]
    terminal_rules: tuple[RuleDraft, ...]
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if (
            self.task_family_index < 1
            or not 1 <= len(self.public_goal_fields) <= 12
            or len(set(self.public_goal_fields)) != len(self.public_goal_fields)
            or not self.success_rules
            or not self.terminal_rules
        ):
            raise ValueError("task_requirement_invalid")


@dataclass(frozen=True, slots=True)
class EvaluatorGoalBinding:
    public_goal_path: str
    evaluator_goal_path: str

    def __post_init__(self) -> None:
        if not all(
            re.fullmatch(r"/(?:[A-Za-z0-9_~-]+(?:/[A-Za-z0-9_~-]+)*)?", path)
            for path in (self.public_goal_path, self.evaluator_goal_path)
        ):
            raise ValueError("evaluator_goal_binding_invalid")


@dataclass(frozen=True, slots=True)
class RewardSpec:
    failure: Literal[-1] = -1
    success: Literal[1] = 1
    otherwise: Literal[0] = 0
    precedence: tuple[Literal["failure", "success", "otherwise"], ...] = (
        "failure",
        "success",
        "otherwise",
    )

    def __post_init__(self) -> None:
        if (self.failure, self.success, self.otherwise, self.precedence) != (
            -1,
            1,
            0,
            ("failure", "success", "otherwise"),
        ):
            raise ValueError("reward_spec_invalid")


@dataclass(frozen=True, slots=True)
class TerminationSpec:
    terminate_on: tuple[Literal["terminal", "success", "failure"], ...] = (
        "terminal",
        "success",
        "failure",
    )
    otherwise: Literal["continue"] = "continue"

    def __post_init__(self) -> None:
        if self.terminate_on != ("terminal", "success", "failure") or self.otherwise != "continue":
            raise ValueError("termination_spec_invalid")


@dataclass(frozen=True, slots=True)
class VerificationRequirements:
    task_family_index: int
    require_materialization: Literal[True]
    required_recipe_digests: tuple[str, ...]
    required_gates: tuple[Literal["task_materialization", "task_reachability"], ...] = (
        "task_materialization",
        "task_reachability",
    )

    def __post_init__(self) -> None:
        if (
            self.task_family_index < 1
            or self.require_materialization is not True
            or not self.required_recipe_digests
            or len(set(self.required_recipe_digests)) != len(self.required_recipe_digests)
            or self.required_gates != ("task_materialization", "task_reachability")
        ):
            raise ValueError("verification_requirements_invalid")
        for digest in self.required_recipe_digests:
            _digest(digest, "verification_recipe_digest_invalid")


@dataclass(frozen=True, slots=True)
class AssuranceRecipe:
    task_family_index: int
    tool_index: int
    task_digest: str
    difficulty_digest: str
    tool_digest: str
    actor: str
    primary_difficulty: tuple[tuple[str, str], ...]
    alternate_difficulty: tuple[tuple[str, str], ...]
    action_tool_indexes: tuple[int, ...]
    recipe_digest: str

    def __post_init__(self) -> None:
        if (
            self.task_family_index < 1
            or self.tool_index < 1
            or not self.actor
            or not self.primary_difficulty
            or not self.alternate_difficulty
            or not self.action_tool_indexes
            or self.tool_index not in self.action_tool_indexes
        ):
            raise ValueError("assurance_recipe_invalid")
        for digest in (
            self.task_digest,
            self.difficulty_digest,
            self.tool_digest,
            self.recipe_digest,
        ):
            _digest(digest, "assurance_recipe_digest_invalid")


@dataclass(frozen=True, slots=True)
class ExecutableTaskContract:
    task_family_index: int
    task_requirement: TaskRequirement
    public_goal_schema: tuple[tuple[str, str], ...]
    initial_config_schema: tuple[tuple[str, str], ...]
    evaluator_goal_bindings: tuple[EvaluatorGoalBinding, ...]
    instruction_template_digest: str
    reward_spec: RewardSpec
    reward_digest: str
    termination_spec: TerminationSpec
    termination_digest: str
    verification_requirements: VerificationRequirements
    verification_digest: str

    def __post_init__(self) -> None:
        if (
            self.task_family_index != self.task_requirement.task_family_index
            or self.task_family_index != self.verification_requirements.task_family_index
            or not self.public_goal_schema
            or not self.initial_config_schema
            or len({binding.public_goal_path for binding in self.evaluator_goal_bindings})
            != len(self.evaluator_goal_bindings)
        ):
            raise ValueError("executable_task_invalid")
        for value, digest, code in (
            (self.reward_spec, self.reward_digest, "reward_digest_invalid"),
            (self.termination_spec, self.termination_digest, "termination_digest_invalid"),
            (
                self.verification_requirements,
                self.verification_digest,
                "verification_digest_invalid",
            ),
        ):
            if digest_value(value) != digest:
                raise ValueError(code)
        _digest(self.instruction_template_digest, "instruction_template_digest_invalid")


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    queries: tuple[str, ...]
    questions_to_resolve: tuple[str, ...]
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if (
            not 1 <= len(self.queries) <= 6
            or len(set(self.queries)) != len(self.queries)
            or any(not query.strip() for query in self.queries)
            or not 1 <= len(self.questions_to_resolve) <= 12
        ):
            raise ValueError("research_plan_invalid")


@dataclass(frozen=True, slots=True)
class DesignContract:
    evidence: EvidenceGraph
    architecture: WorldArchitecture
    shared_tool_contracts: tuple[SharedToolContract, ...]
    tools: tuple[ToolDraft, ...]
    world_rules: WorldRuleSet
    curriculum: CurriculumPlan
    task_requirements: tuple[TaskRequirement, ...]
    executable_tasks: tuple[ExecutableTaskContract, ...]
    assurance_recipes: tuple[AssuranceRecipe, ...]
    artifact: ArtifactRef
    work_refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        tool_indexes = tuple(tool.tool_index for tool in self.tools)
        if tool_indexes != tuple(range(1, len(self.tools) + 1)):
            raise ValueError("design_tool_order_invalid")
        catalog_indexes = {binding.index for binding in self.architecture.catalog.bindings}
        citation_indexes = {item.index for item in self.evidence.catalog.items}
        if any(
            family.actor_index > len(self.architecture.boundary.actors)
            or not set(family.tool_indexes).issubset(tool_indexes)
            or not set(family.citation_indexes).issubset(citation_indexes)
            for family in self.curriculum.families
        ) or any(
            not set(task.public_goal_fields).issubset(catalog_indexes)
            for task in self.task_requirements
        ):
            raise ValueError("design_reference_invalid")
        family_indexes = tuple(family.task_family_index for family in self.curriculum.families)
        if tuple(task.task_family_index for task in self.task_requirements) != family_indexes:
            raise ValueError("design_task_order_invalid")
        if tuple(task.task_family_index for task in self.executable_tasks) != family_indexes:
            raise ValueError("design_executable_task_order_invalid")
        if (
            tuple(contract.tool_indexes for contract in self.shared_tool_contracts)
            != self.architecture.coupling_plan.groups
        ):
            raise ValueError("design_shared_contract_order_invalid")
        shared = {contract.digest: contract for contract in self.shared_tool_contracts}
        for tool in self.tools:
            group = next(
                (
                    contract
                    for contract in self.shared_tool_contracts
                    if tool.tool_index in contract.tool_indexes
                ),
                None,
            )
            if (
                (group is None and tool.shared_contract_digest is not None)
                or (group is not None and tool.shared_contract_digest != group.digest)
                or (
                    tool.shared_contract_digest is not None
                    and tool.shared_contract_digest not in shared
                )
            ):
                raise ValueError("design_shared_contract_reference_invalid")
        expected_pairs = tuple(
            (family.task_family_index, tool_index)
            for family in self.curriculum.families
            for tool_index in family.tool_indexes
        )
        actual_pairs = tuple(
            (recipe.task_family_index, recipe.tool_index) for recipe in self.assurance_recipes
        )
        if actual_pairs != expected_pairs:
            raise ValueError("design_assurance_recipe_order_invalid")
        recipes = {
            pair: recipe.recipe_digest
            for pair, recipe in zip(actual_pairs, self.assurance_recipes, strict=True)
        }
        for family, task in zip(self.curriculum.families, self.executable_tasks, strict=True):
            expected = tuple(
                recipes[(family.task_family_index, tool)] for tool in family.tool_indexes
            )
            if task.verification_requirements.required_recipe_digests != expected:
                raise ValueError("design_verification_recipe_binding_invalid")


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    entrypoint: str
    source_digest: str
    files: tuple[dict[str, Any], ...]
    artifact: ArtifactRef
    materializer_entrypoint: str = "materializer.py"
    work_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierCommitment:
    """Public, non-replayable commitment to one framework-owned verifier family."""

    commitment_id: str
    task_family_index: int
    tool_index: int
    variation_kind: VerifierFamily
    argument_index: int | None
    risk: str
    baseline_recipe_digest: str

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"verifier-[a-z0-9-]{1,76}", self.commitment_id)
            or self.task_family_index < 1
            or self.tool_index < 1
            or not self.risk.strip()
            or len(self.risk) > 280
        ):
            raise ValueError("verifier_commitment_invalid")
        _digest(self.baseline_recipe_digest, "verifier_commitment_recipe_digest_invalid")
        if self.variation_kind == "argument_variation":
            if self.argument_index is None or self.argument_index < 1:
                raise ValueError("verifier_commitment_argument_invalid")
        elif self.argument_index is not None:
            raise ValueError("verifier_commitment_argument_invalid")


@dataclass(frozen=True, slots=True)
class VerifierBundle:
    """Persisted verifier projection; private cases never cross this boundary."""

    commitments: tuple[VerifierCommitment, ...]
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if not self.commitments or len({item.commitment_id for item in self.commitments}) != len(
            self.commitments
        ):
            raise ValueError("verifier_bundle_commitment_invalid")


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: GateStatus
    code: str | None
    evidence: ArtifactRef | None


@dataclass(frozen=True, slots=True)
class JudgeReport:
    candidate_digest: str
    gates: tuple[GateResult, ...]
    artifact: ArtifactRef
    integration_ref: ArtifactRef | None = None
    verifier_ref: ArtifactRef | None = None

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(gate.status == "passed" for gate in self.gates)

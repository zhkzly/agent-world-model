"""Structured outputs requested from the two Designer-facing Agent profiles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic_core import PydanticCustomError

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    register_agent_output_contract,
)
from agent_world.contracts import (
    MAX_ACTORS_PER_TASK,
    MAX_DIFFICULTY_DIMENSIONS,
    MAX_DISTINCT_CURRICULUM_SAMPLES,
    ArtifactRef,
    BudgetUsage,
    Claim,
    ConcurrencySemantics,
    ContentHash,
    CoverageDimension,
    CurriculumRequirements,
    DifficultyDimension,
    Evidence,
    EvidenceConflict,
    FidelityStatement,
    IdempotencyMode,
    IdempotencySemantics,
    Identifier,
    ObservationSemantics,
    PermissionRule,
    RetrySemantics,
    RewardSpec,
    RollbackSemantics,
    Rule,
    RuleFamily,
    RuleValueSource,
    RuleValueType,
    StateEntitySchema,
    StateSchema,
    TimeoutSemantics,
    ToolContract,
    ToolError,
    ToolSemantics,
    ToolSurface,
    TransactionSemantics,
    V2Contract,
    VerificationRequirements,
    WorldBoundary,
)


class AgentOutput(SemanticAdvisoryOutput, BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


# A real ToolSemantics turn exhausted a Provider-owned structured-output
# envelope after sustained progress.  The framework must not pretend that its
# logical budget is a physical Provider cap.  Instead the physical boundary is
# one complete tool: cross-tool facts are frozen by SharedToolSemantics first,
# and independent singleton leaves may then be scheduled within configured
# capacity.  This is topology, not a request for the Agent to invent less
# business meaning.
MAX_TOOLS_PER_SEMANTICS_BATCH = 1
MAX_SEMANTICS_BATCHES = 8


class PlannedSearchQuery(AgentOutput):
    text: Annotated[str, Field(min_length=1)]
    rationale: Annotated[str, Field(min_length=1)]
    language: str = "all"
    topics: tuple[str, ...] = ()


class ResearchPlan(AgentOutput):
    queries: Annotated[tuple[PlannedSearchQuery, ...], Field(min_length=1, max_length=12)]
    target_coverage_dimensions: Annotated[tuple[str, ...], Field(min_length=1)]
    known_source_urls: tuple[str, ...] = ()
    stop_conditions: Annotated[tuple[str, ...], Field(min_length=1)]


class ResearchAcquisition(V2Contract):
    """Durable real-tools closure consumed by one EvidenceSynthesis leaf.

    The record contains only normalized evidence and content-addressed refs.
    Query text, provider response bodies and credentials remain in the bounded
    research Artifact closure rather than in Scheduler control state.
    """

    acquisition_id: str
    plan_ref: ArtifactRef
    request_ref: ArtifactRef
    evidence: tuple[Evidence, ...]
    source_refs: tuple[ArtifactRef, ...]
    passage_pack_ref: ArtifactRef
    usage: BudgetUsage

    @model_validator(mode="after")
    def validate_acquisition(self) -> ResearchAcquisition:
        if self.plan_ref.artifact_type != "design.research_plan":
            raise PydanticCustomError(
                "research_acquisition_plan_ref_type",
                "ResearchAcquisition must bind one ResearchPlan",
            )
        if self.request_ref.artifact_type != "control.environment_request":
            raise PydanticCustomError(
                "research_acquisition_request_ref_type",
                "ResearchAcquisition must bind one EnvironmentRequest",
            )
        if self.passage_pack_ref.artifact_type != "design.evidence_passage_pack":
            raise PydanticCustomError(
                "research_acquisition_passage_pack_ref_type",
                "ResearchAcquisition must bind one EvidencePassagePack",
            )
        if not self.evidence or not self.source_refs:
            raise PydanticCustomError(
                "research_acquisition_evidence_missing",
                "ResearchAcquisition requires normalized evidence and source refs",
            )
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise PydanticCustomError(
                "research_acquisition_evidence_id_duplicate",
                "ResearchAcquisition evidence ids must be unique",
            )
        if len(set(self.source_refs)) != len(self.source_refs):
            raise PydanticCustomError(
                "research_acquisition_source_ref_duplicate",
                "ResearchAcquisition source refs must be unique",
            )
        if self.usage.search_calls < 1 or self.usage.tool_calls < self.usage.search_calls:
            raise PydanticCustomError(
                "research_acquisition_usage_accounting",
                "ResearchAcquisition usage must retain real tool accounting",
            )
        return self


class EvidenceClaimSourceDraft(AgentOutput):
    """Agent-authored claim meaning with framework-bound evidence selection.

    Evidence identifiers are durable framework mechanics, not research meaning.
    The Researcher therefore selects a one-based entry from the frozen citation
    catalog; the compiler later restores the exact immutable evidence id.
    """

    claim_id: Identifier
    kind: Literal["observed", "inference", "product_decision", "bounded_assumption"]
    statement: Annotated[str, Field(min_length=1)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence_catalog_indexes: tuple[Annotated[int, Field(ge=1)], ...] = ()
    supports_claim_ids: tuple[Identifier, ...] = ()
    contradicts_claim_ids: tuple[Identifier, ...] = ()
    claim_status: Literal["supported", "contested", "unresolved", "superseded"] = "unresolved"
    risk: Literal["low", "medium", "high", "critical"] = "medium"


class EvidenceConflictSourceDraft(AgentOutput):
    """Agent-authored conflict meaning over Agent-owned claim identifiers."""

    conflict_id: Identifier
    claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=2)]
    description: Annotated[str, Field(min_length=1)]
    resolution: Annotated[str, Field(min_length=1)] | None = None


class EvidenceSynthesisSourceDraft(AgentOutput):
    """One Researcher proposal before framework evidence-id compilation."""

    claims: tuple[EvidenceClaimSourceDraft, ...]
    conflicts: tuple[EvidenceConflictSourceDraft, ...] = ()
    unresolved_questions: tuple[Annotated[str, Field(min_length=1)], ...] = ()


class EvidenceSynthesis(V2Contract):
    """Canonical synthesis after citation positions map to frozen evidence ids."""

    claims: tuple[Claim, ...]
    conflicts: tuple[EvidenceConflict, ...] = ()
    unresolved_questions: tuple[str, ...] = ()


class AssumptionIssueOrigin(AgentOutput):
    """One exact artifact field that exposes a release-blocking uncertainty."""

    source: Literal[
        "evidence_graph",
        "environment_design",
        "world_spec",
        "coverage_dimension",
    ]
    coverage_dimension: Identifier | None = None

    @model_validator(mode="after")
    def validate_coverage_dimension(self) -> AssumptionIssueOrigin:
        if (self.source == "coverage_dimension") != (self.coverage_dimension is not None):
            raise PydanticCustomError(
                "assumption_origin_coverage_dimension_binding",
                "coverage_dimension is required only for coverage_dimension origins",
            )
        return self


class AssumptionIssue(AgentOutput):
    """A deduplicated uncertainty with every artifact origin retained."""

    issue_id: Identifier
    statement: Annotated[str, Field(min_length=1)]
    origins: Annotated[tuple[AssumptionIssueOrigin, ...], Field(min_length=1)]


class AssumptionResolutionDraft(AgentOutput):
    """One explicit disposition for a previously recorded evidence question."""

    issue_id: Identifier
    question: Annotated[str, Field(min_length=1)]
    disposition: Literal["product_decision", "bounded_out_of_scope", "needs_human"]
    rationale: Annotated[str, Field(min_length=1)]
    claim: Claim | None = None
    fidelity: FidelityStatement | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> AssumptionResolutionDraft:
        if self.disposition == "needs_human":
            if self.claim is not None or self.fidelity is not None:
                raise PydanticCustomError(
                    "assumption_needs_human_payload_forbidden",
                    "needs_human requires null claim and fidelity",
                )
            return self
        if self.claim is None or self.fidelity is None:
            raise PydanticCustomError(
                "assumption_closure_payload_required",
                "closed resolution requires both claim and fidelity",
            )
        expected_kind = (
            "product_decision" if self.disposition == "product_decision" else "bounded_assumption"
        )
        expected_level = (
            "synthetic_policy"
            if self.disposition == "product_decision"
            else "bounded_approximation"
        )
        if self.claim.kind != expected_kind or self.claim.status != "supported":
            raise PydanticCustomError(
                "assumption_claim_disposition_mismatch",
                "claim kind/status must match disposition and be supported",
            )
        if self.fidelity.level != expected_level:
            raise PydanticCustomError(
                "assumption_fidelity_level_mismatch",
                "fidelity level must match the selected disposition",
            )
        if self.claim.claim_id not in self.fidelity.evidence_claim_ids:
            raise PydanticCustomError(
                "assumption_fidelity_claim_missing",
                "fidelity evidence_claim_ids must include the closure claim id",
            )
        if self.disposition == "bounded_out_of_scope" and not self.fidelity.known_divergence:
            raise PydanticCustomError(
                "assumption_known_divergence_required",
                "bounded_out_of_scope requires a non-empty known_divergence",
            )
        return self


class EvidenceAssumptionClosureDraft(AgentOutput):
    """Bounded closure decisions for every frozen EvidenceGraph question."""

    resolutions: Annotated[
        tuple[AssumptionResolutionDraft, ...], Field(min_length=1, max_length=32)
    ]


class ToolSurfaceDraft(AgentOutput):
    """One evidence-bound public tool shape before behavior is authored."""

    surface: ToolSurface
    evidence_claim_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class WorldBoundaryDraft(AgentOutput):
    """World identity, authority, dimensions, and fidelity before state design."""

    boundary: WorldBoundary
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]


class TaskDimensionsDraft(AgentOutput):
    """Stable compiler identifiers for one frozen human-readable dimension taxonomy."""

    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class WorldStateDraft(AgentOutput):
    """State model compiled against one frozen WorldBoundary."""

    state: StateSchema


class WorldStateShapeDraft(AgentOutput):
    """Entity and root schemas without executable initial-state rules."""

    entities: Annotated[tuple[StateEntitySchema, ...], Field(min_length=1, max_length=32)]
    root_state_schema: dict[str, JsonValue]


class StateEntityPlan(AgentOutput):
    """One bounded semantic unit selected before its JSON Schema is authored."""

    entity: Identifier
    purpose: Annotated[str, Field(min_length=1)]
    root_field: Identifier
    storage: Literal["collection", "singleton"]
    system_of_record: Identifier
    boundary_resource_ids: tuple[Identifier, ...] = ()
    primary_key_fields: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    mutable_fields: tuple[Identifier, ...] = ()
    lifecycle_field: Identifier | None = None
    lifecycle_states: tuple[Identifier, ...] = ()
    evidence_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class StateEntityInventoryDraft(AgentOutput):
    """Normalized entity ownership and identity, without recursive schemas."""

    entities: Annotated[tuple[StateEntityPlan, ...], Field(min_length=1, max_length=12)]


class StateEntitySchemaDraft(AgentOutput):
    """Framework-compiled JSON Schema for exactly one frozen entity plan."""

    entity: Identifier
    json_schema: dict[str, JsonValue]


class InitialStateRulesDraft(AgentOutput):
    """Executable reset invariants compiled against one frozen state shape."""

    initial_state_constraints: tuple[Rule, ...] = ()


class WorldToolInventoryDraft(AgentOutput):
    """Frozen public ToolSurfaces compiled against boundary and state."""

    tool_surfaces: Annotated[tuple[ToolSurfaceDraft, ...], Field(min_length=1, max_length=8)]


class ToolSurfacePlan(AgentOutput):
    """One frozen public tool identity before its schemas are authored."""

    tool_id: Identifier
    namespace: Identifier
    name: Identifier
    description: Annotated[str, Field(min_length=1)]
    transport: Literal["runtime", "mcp", "http", "cli", "python", "database"]
    reads_state_entities: tuple[Identifier, ...] = ()
    writes_state_entities: tuple[Identifier, ...] = ()
    evidence_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_state_footprint(self) -> ToolSurfacePlan:
        if len(set(self.reads_state_entities)) != len(self.reads_state_entities):
            raise PydanticCustomError(
                "tool_plan_read_state_duplicate",
                "tool plan read-state entities must be unique",
            )
        if len(set(self.writes_state_entities)) != len(self.writes_state_entities):
            raise PydanticCustomError(
                "tool_plan_write_state_duplicate",
                "tool plan write-state entities must be unique",
            )
        if not (self.reads_state_entities or self.writes_state_entities):
            raise PydanticCustomError(
                "tool_plan_state_footprint_empty",
                "tool plan must declare a non-empty read/write state footprint",
            )
        return self


class WorldToolPlanInventoryDraft(AgentOutput):
    """Bounded tool identities and evidence bindings, without recursive schemas."""

    tools: Annotated[tuple[ToolSurfacePlan, ...], Field(min_length=1, max_length=8)]


class CompactFieldSemanticDraft(AgentOutput):
    """Business meaning for one flat field; framework owns schema graph syntax."""

    name: Identifier
    value_type: Literal["string", "integer", "number", "boolean"]
    description: Annotated[str, Field(min_length=1)]
    required: bool = True
    nullable: bool = False
    repeated: bool = False
    string_format: Literal["none", "date", "date-time", "email", "uri", "uuid"] = "none"
    enum_values: Annotated[tuple[str, ...], Field(max_length=32)] = ()
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_type_constraints(self) -> CompactFieldSemanticDraft:
        if self.value_type != "string" and (self.string_format != "none" or self.enum_values):
            raise PydanticCustomError(
                "compact_field_string_constraints",
                "string_format and enum_values require value_type=string",
            )
        if self.value_type not in {"integer", "number"} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise PydanticCustomError(
                "compact_field_numeric_bounds",
                "minimum and maximum require value_type=integer or number",
            )
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise PydanticCustomError(
                "compact_field_bounds_order",
                "minimum cannot exceed maximum",
            )
        if len(set(self.enum_values)) != len(self.enum_values):
            raise PydanticCustomError(
                "compact_field_enum_unique",
                "enum_values must not contain duplicates",
            )
        return self


class ToolInterfaceSourceDraft(AgentOutput):
    """Schema meaning owned by exactly one enclosing tool source."""

    input_fields: Annotated[tuple[CompactFieldSemanticDraft, ...], Field(max_length=32)] = ()
    output_fields: Annotated[tuple[CompactFieldSemanticDraft, ...], Field(max_length=32)] = ()
    observation_fields: Annotated[tuple[CompactFieldSemanticDraft, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def validate_field_sets(self) -> ToolInterfaceSourceDraft:
        for role, fields in (
            ("input", self.input_fields),
            ("output", self.output_fields),
            ("observation", self.observation_fields),
        ):
            names = tuple(item.name for item in fields)
            if len(set(names)) != len(names):
                # ``role`` is a framework literal from the tuple above, never
                # Agent-supplied text, so it is safe inside a stable code.
                raise PydanticCustomError(
                    f"tool_interface_{role}_field_name_duplicate",
                    "tool interface field names must be unique within one role",
                )
        if not (self.output_fields or self.observation_fields):
            raise PydanticCustomError(
                "tool_interface_result_fields_missing",
                "tool interface requires output or observation fields",
            )
        return self


class ToolSurfaceSourceDraft(AgentOutput):
    """Agent-owned tool meaning; framework derives the canonical tool id."""

    namespace: Identifier
    name: Identifier
    description: Annotated[str, Field(min_length=1)]
    transport: Literal["runtime", "mcp", "http", "cli", "python", "database"]
    reads_state_entities: tuple[Identifier, ...] = ()
    writes_state_entities: tuple[Identifier, ...] = ()
    evidence_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    interface: ToolInterfaceSourceDraft

    @property
    def tool_id(self) -> str:
        return f"{self.namespace}.{self.name}"

    @model_validator(mode="after")
    def validate_state_footprint(self) -> ToolSurfaceSourceDraft:
        if len(set(self.reads_state_entities)) != len(self.reads_state_entities):
            raise PydanticCustomError(
                "tool_source_read_state_duplicate",
                "tool source read-state entities must be unique",
            )
        if len(set(self.writes_state_entities)) != len(self.writes_state_entities):
            raise PydanticCustomError(
                "tool_source_write_state_duplicate",
                "tool source write-state entities must be unique",
            )
        if not (self.reads_state_entities or self.writes_state_entities):
            raise PydanticCustomError(
                "tool_source_state_footprint_empty",
                "tool source must declare a non-empty read/write state footprint",
            )
        return self


class WorldToolSourceInventoryDraft(AgentOutput):
    tools: Annotated[tuple[ToolSurfaceSourceDraft, ...], Field(min_length=1, max_length=8)]


class ToolSurfaceSchemasDraft(AgentOutput):
    """Three locally closed schemas for exactly one frozen tool plan."""

    tool_id: Identifier
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    observation_schema: dict[str, JsonValue]


class ToolSchemaDraft(AgentOutput):
    """One locally closed schema for one frozen tool and schema role."""

    tool_id: Identifier
    schema_kind: Literal["input", "output", "observation"]
    json_schema: dict[str, JsonValue]


class SchemaPropertyDraft(AgentOutput):
    name: Identifier
    node_id: Identifier
    required: bool


class SchemaObjectNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["object"]
    description: str | None = None
    properties: Annotated[tuple[SchemaPropertyDraft, ...], Field(max_length=64)] = ()


class SchemaArrayNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["array"]
    description: str | None = None
    items_node_id: Identifier
    min_items: Annotated[int | None, Field(ge=0)] = None
    max_items: Annotated[int | None, Field(ge=0)] = None


class SchemaStringNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["string"]
    description: str | None = None
    format: Literal["none", "date", "date-time", "email", "uri", "uuid"] = "none"
    enum_values: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    const_value: str | None = None
    min_length: Annotated[int | None, Field(ge=0)] = None
    max_length: Annotated[int | None, Field(ge=0)] = None


class SchemaIntegerNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["integer"]
    description: str | None = None
    enum_values: Annotated[tuple[int, ...], Field(max_length=64)] = ()
    const_value: int | None = None
    minimum: int | None = None
    maximum: int | None = None


class SchemaNumberNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["number"]
    description: str | None = None
    const_value: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class SchemaBooleanNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["boolean"]
    description: str | None = None
    const_value: bool | None = None


class SchemaNullNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["null"]
    description: str | None = None


class SchemaUnionNodeDraft(AgentOutput):
    node_id: Identifier
    kind: Literal["union"]
    description: str | None = None
    variant_node_ids: Annotated[tuple[Identifier, ...], Field(min_length=2, max_length=16)]


SchemaNodeDraft = Annotated[
    SchemaObjectNodeDraft
    | SchemaArrayNodeDraft
    | SchemaStringNodeDraft
    | SchemaIntegerNodeDraft
    | SchemaNumberNodeDraft
    | SchemaBooleanNodeDraft
    | SchemaNullNodeDraft
    | SchemaUnionNodeDraft,
    Field(discriminator="kind"),
]


class StateEntitySchemaIRDraft(AgentOutput):
    """Shape-only semantic entity graph; Designer preflight owns graph invariants."""

    entity: Identifier
    root_node_id: Identifier
    nodes: Annotated[tuple[SchemaNodeDraft, ...], Field(min_length=1, max_length=128)]


class RuleConstantDraft(AgentOutput):
    """One unvalidated JSON constant authored at the Agent boundary."""

    kind: Literal["constant"]
    value_type: Literal["null", "boolean", "number", "string", "array", "object"]
    value: JsonValue


class RuleReferenceDraft(AgentOutput):
    """One reference whose pointer/type closure is checked by the framework compiler."""

    kind: Literal["reference"]
    source: RuleValueSource
    pointer: str = ""
    value_type: RuleValueType


class RuleBoundReferenceDraft(AgentOutput):
    """One ToolSemantics reference selected from a frozen framework catalog.

    The Agent chooses *which* visible business value matters.  The catalog id
    is then deterministically expanded into source, RFC 6901 pointer, and
    value type before executable Rule IR is compiled.  Raw reference fields
    remain available only to source boundaries whose schema is not frozen yet
    (for example task-local goal semantics).
    """

    kind: Literal["bound_reference"]
    binding_id: Identifier


RuleLookupKeyDraft = Annotated[
    RuleConstantDraft | RuleReferenceDraft | RuleBoundReferenceDraft,
    Field(discriminator="kind"),
]


class RuleLookupByKeyDraft(AgentOutput):
    """Bounded state-collection selector compiled into executable Rule IR."""

    kind: Literal["lookup_by_key"]
    source: Literal["pre_state", "post_state"]
    collection_pointer: str
    key_field: Identifier
    key: RuleLookupKeyDraft
    value_pointer: str = ""
    value_type: RuleValueType


class RuleBoundLookupByKeyDraft(AgentOutput):
    """One frozen collection-field selection for ToolSemantics.

    ``binding_id`` owns collection pointer, primary key, selected item field,
    source, and value type as one indivisible framework fact.  The Agent can
    still choose the business relation and supply its key expression, but it
    cannot accidentally splice a collection from one entity to a field or key
    from another.
    """

    kind: Literal["bound_lookup_by_key"]
    binding_id: Identifier
    key: RuleLookupKeyDraft


RuleAtomDraft = Annotated[
    RuleConstantDraft
    | RuleReferenceDraft
    | RuleBoundReferenceDraft
    | RuleLookupByKeyDraft
    | RuleBoundLookupByKeyDraft,
    Field(discriminator="kind"),
]


class RuleArithmeticDraft(AgentOutput):
    """Bounded non-recursive arithmetic authored without hidden validators."""

    kind: Literal["arithmetic"]
    operator: Literal["add", "subtract", "multiply", "divide", "modulo"]
    left: RuleAtomDraft
    right: RuleAtomDraft


RuleTermDraft = Annotated[
    RuleConstantDraft
    | RuleReferenceDraft
    | RuleBoundReferenceDraft
    | RuleLookupByKeyDraft
    | RuleBoundLookupByKeyDraft
    | RuleArithmeticDraft,
    Field(discriminator="kind"),
]


class RuleExistsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["exists"]
    left: RuleReferenceDraft
    negate: bool = False


class RuleNotExistsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["not_exists"]
    left: RuleReferenceDraft
    negate: bool = False


class RuleSchemaClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["schema_valid"]
    left: RuleTermDraft
    json_schema: dict[str, JsonValue]
    negate: bool = False


class RuleEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["equal"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleNotEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["not_equal"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleGreaterThanClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["greater_than"]
    ordering: Literal["number", "date", "date-time"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleGreaterOrEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["greater_or_equal"]
    ordering: Literal["number", "date", "date-time"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleLessThanClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["less_than"]
    ordering: Literal["number", "date", "date-time"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleLessOrEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["less_or_equal"]
    ordering: Literal["number", "date", "date-time"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleContainsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["contains"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


class RuleNotContainsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["not_contains"]
    left: RuleTermDraft
    right: RuleTermDraft
    negate: bool = False


RuleClauseDraft = Annotated[
    RuleExistsClauseDraft
    | RuleNotExistsClauseDraft
    | RuleSchemaClauseDraft
    | RuleEqualClauseDraft
    | RuleNotEqualClauseDraft
    | RuleGreaterThanClauseDraft
    | RuleGreaterOrEqualClauseDraft
    | RuleLessThanClauseDraft
    | RuleLessOrEqualClauseDraft
    | RuleContainsClauseDraft
    | RuleNotContainsClauseDraft,
    Field(discriminator="operator"),
]


class RuleDraft(AgentOutput):
    """Agent-facing Rule ADT deterministically compiled into the core Rule IR."""

    # A rule id names a framework IR object; it is not business semantics.
    # ToolSemanticsBatch, WorldRules, and TaskCurriculum derive it from their
    # frozen section and ordinal before a proposal is persisted or compiled.
    # A later compiled semantic source may carry that framework-derived ID, but
    # an Agent-facing source draft must never need to guess one.
    rule_id: Identifier | None = None
    family: RuleFamily
    description: Annotated[str, Field(min_length=1)]
    boolean_operator: Literal["all", "any"]
    clauses: Annotated[tuple[RuleClauseDraft, ...], Field(min_length=1, max_length=64)]
    case_sensitivity: Literal["positive_only", "positive_and_negative"]
    evidence_claim_ids: tuple[Identifier, ...] = ()


class ToolRuleBoundLookupByReferenceDraft(AgentOutput):
    """One frozen lookup plus its mechanically compatible reference key.

    ToolSemantics uses a deliberately flat wire representation.  The lookup
    and reference key are one framework-derived catalog selection, so the
    Agent cannot combine two individually valid aliases into an invalid pair.
    """

    kind: Literal["bound_lookup_by_reference"]
    binding_id: Identifier


class ToolRuleBoundLookupByConstantDraft(AgentOutput):
    """One frozen lookup whose key is an explicitly typed JSON constant."""

    kind: Literal["bound_lookup_by_constant"]
    binding_id: Identifier
    key_value_type: Literal["null", "boolean", "number", "string", "array", "object"]
    key_value: JsonValue


ToolRuleAtomDraft = Annotated[
    RuleConstantDraft
    | RuleBoundReferenceDraft
    | ToolRuleBoundLookupByReferenceDraft
    | ToolRuleBoundLookupByConstantDraft,
    Field(discriminator="kind"),
]


class ToolRuleArithmeticDraft(AgentOutput):
    """Bounded ToolSemantics arithmetic over closed, non-recursive atoms."""

    kind: Literal["arithmetic"]
    operator: Literal["add", "subtract", "multiply", "divide", "modulo"]
    left: ToolRuleAtomDraft
    right: ToolRuleAtomDraft


ToolRuleTermDraft = Annotated[
    RuleConstantDraft
    | RuleBoundReferenceDraft
    | ToolRuleBoundLookupByReferenceDraft
    | ToolRuleBoundLookupByConstantDraft
    | ToolRuleArithmeticDraft,
    Field(discriminator="kind"),
]


class ToolRuleEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["equal"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleNotEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["not_equal"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleGreaterThanClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["greater_than"]
    ordering: Literal["number", "date", "date-time"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleGreaterOrEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["greater_or_equal"]
    ordering: Literal["number", "date", "date-time"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleLessThanClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["less_than"]
    ordering: Literal["number", "date", "date-time"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleLessOrEqualClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["less_or_equal"]
    ordering: Literal["number", "date", "date-time"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleContainsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["contains"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


class ToolRuleNotContainsClauseDraft(AgentOutput):
    clause_id: Identifier
    operator: Literal["not_contains"]
    left: ToolRuleTermDraft
    right: ToolRuleTermDraft
    negate: bool = False


ToolRuleClauseDraft = Annotated[
    ToolRuleEqualClauseDraft
    | ToolRuleNotEqualClauseDraft
    | ToolRuleGreaterThanClauseDraft
    | ToolRuleGreaterOrEqualClauseDraft
    | ToolRuleLessThanClauseDraft
    | ToolRuleLessOrEqualClauseDraft
    | ToolRuleContainsClauseDraft
    | ToolRuleNotContainsClauseDraft,
    Field(discriminator="operator"),
]


class ToolRuleDraft(AgentOutput):
    """Closed ToolSemantics wire Rule compiled into the general RuleDraft IR.

    WorldRules, Curriculum, and other non-frozen contexts retain RuleDraft.
    This narrower source exists only where framework code has already frozen a
    complete reference and collection-binding catalog for one tool.
    """

    # In ToolSemantics this is a structural label fixed by the enclosing
    # section, not Agent-authored semantics.  Keep it in the materialized IR
    # for the shared Rule compiler, but make the wire field optional and let
    # ToolSemanticSourceDraft derive it after parsing.
    family: Literal[
        "precondition",
        "transition",
        "postcondition",
        "error_condition",
        "permission",
    ] = "precondition"
    description: Annotated[str, Field(min_length=1)]
    boolean_operator: Literal["all", "any"]
    clauses: Annotated[tuple[ToolRuleClauseDraft, ...], Field(min_length=1, max_length=64)]
    case_sensitivity: Literal["positive_only", "positive_and_negative"]
    evidence_claim_ids: tuple[Identifier, ...] = ()


def _with_tool_rule_family(
    rule: ToolRuleDraft,
    family: Literal[
        "precondition",
        "transition",
        "postcondition",
        "error_condition",
        "permission",
    ],
) -> ToolRuleDraft:
    """Return one ToolSemantics Rule with its framework-owned section label."""

    return rule.model_copy(update={"family": family})


class ToolErrorSourceDraft(AgentOutput):
    error_code: Identifier
    when: RuleDraft
    observation: Annotated[str, Field(min_length=1)]
    state_effect: Literal["none", "partial", "rolled_back", "unknown"]
    retryable: bool
    evidence_claim_ids: tuple[Identifier, ...] = ()


class PermissionRuleSourceDraft(AgentOutput):
    """Agent-owned permission meaning without a duplicated actor-set field.

    The keys of ``required_scopes_by_actor`` are the complete set of actors
    admitted by this permission. The core ``PermissionRule`` retains its
    explicit ``allowed_actors`` field for Runtime/Judge consumption, but the
    compiler derives that mechanical projection from these keys.
    """

    permission_id: Identifier
    required_scopes_by_actor: Annotated[
        dict[Identifier, tuple[Identifier, ...]], Field(min_length=1)
    ]
    condition: RuleDraft | None = None
    denied_observation: Annotated[str, Field(min_length=1)]


class ObservationSemanticsSourceDraft(AgentOutput):
    """Agent chooses visibility; framework derives the exact redacted complement."""

    visible_fields_by_actor: dict[Identifier, tuple[Identifier, ...]]
    consistency: Literal["strong", "read_after_write", "eventual", "snapshot"]
    staleness_bound_seconds: Annotated[float | None, Field(ge=0)] = None


class IdempotencyUnsupportedDraft(AgentOutput):
    mode: Literal["not_supported"]
    duplicate_observation: Annotated[str, Field(min_length=1)]


class IdempotencyNaturalDraft(AgentOutput):
    mode: Literal["natural"]
    duplicate_observation: Annotated[str, Field(min_length=1)]


class IdempotencyKeyDraft(AgentOutput):
    mode: Literal["idempotency_key"]
    key_field: Identifier
    retention_seconds: Annotated[float | None, Field(gt=0)] = None
    duplicate_observation: Annotated[str, Field(min_length=1)]


IdempotencySourceDraft = Annotated[
    IdempotencyUnsupportedDraft | IdempotencyNaturalDraft | IdempotencyKeyDraft,
    Field(discriminator="mode"),
]


class ToolSchemaIRDraft(AgentOutput):
    """Shape-only tool schema graph; Designer preflight owns graph invariants."""

    tool_id: Identifier
    schema_kind: Literal["input", "output", "observation"]
    root_node_id: Identifier
    nodes: Annotated[tuple[SchemaNodeDraft, ...], Field(min_length=1, max_length=128)]


class WorldSkeletonDraft(AgentOutput):
    """Compact world identity/state/tool inventory shared by semantic nodes."""

    boundary: WorldBoundary
    state: StateSchema
    tool_surfaces: Annotated[tuple[ToolSurfaceDraft, ...], Field(min_length=1, max_length=8)]
    task_dimensions: Annotated[tuple[str, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]


class ToolBehaviorDraft(AgentOutput):
    """Framework-composed state-transition and error behavior for one tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    preconditions: tuple[Rule, ...] = ()
    transition: Annotated[tuple[Rule, ...], Field(min_length=1)]
    postconditions: tuple[Rule, ...] = ()
    errors: tuple[ToolError, ...] = ()


class ToolConditionsDraft(AgentOutput):
    """Preconditions and postconditions for one frozen tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    preconditions: tuple[Rule, ...] = ()
    postconditions: tuple[Rule, ...] = ()


class ToolStateTransitionDraft(AgentOutput):
    """Executable pre-state/argument to post-state/output constraints for one tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    transition: Annotated[tuple[Rule, ...], Field(min_length=1)]


class ToolErrorsDraft(AgentOutput):
    """Declared error conditions for one frozen tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    errors: Annotated[tuple[ToolError, ...], Field(min_length=1)]


class InitialStateRulesSourceDraft(AgentOutput):
    """Agent-authored reset rules before deterministic Rule compilation."""

    initial_state_constraints: tuple[RuleDraft, ...] = ()


class ToolConditionsSourceDraft(AgentOutput):
    tool_id: Identifier
    preconditions: tuple[RuleDraft, ...] = ()
    postconditions: tuple[RuleDraft, ...] = ()


class ToolStateTransitionSourceDraft(AgentOutput):
    tool_id: Identifier
    transition: Annotated[tuple[RuleDraft, ...], Field(min_length=1)]


class ToolErrorsSourceDraft(AgentOutput):
    tool_id: Identifier
    errors: Annotated[tuple[ToolErrorSourceDraft, ...], Field(min_length=1)]


class ToolAccessObservationDraft(AgentOutput):
    """Actor authority and Agent-visible observation behavior for one tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    permission: PermissionRule
    observation: ObservationSemantics


class ToolAccessObservationSourceDraft(AgentOutput):
    tool_id: Identifier
    permission: PermissionRuleSourceDraft
    observation: ObservationSemanticsSourceDraft


class ToolReliabilityDraft(AgentOutput):
    """Retry, timeout, transaction, rollback, and concurrency behavior for one tool."""

    tool_id: Annotated[str, Field(min_length=1)]
    idempotency: IdempotencySemantics
    retry: RetrySemantics
    timeout: TimeoutSemantics
    transaction: TransactionSemantics
    rollback: RollbackSemantics
    concurrency: ConcurrencySemantics


class ToolReliabilitySourceDraft(AgentOutput):
    tool_id: Identifier
    idempotency: IdempotencySourceDraft
    retry: RetrySemantics
    timeout: TimeoutSemantics
    transaction: TransactionSemantics
    rollback: RollbackSemantics
    concurrency: ConcurrencySemantics


class ToolSemanticsDraft(AgentOutput):
    """Framework-composed complete executable behavior for one frozen ToolSurface."""

    tool_id: Annotated[str, Field(min_length=1)]
    semantics: ToolSemantics


class WorldClosureDraft(AgentOutput):
    """Global invariants authored after all tool contracts are visible."""

    invariants: tuple[Rule, ...]


class WorldClosureSourceDraft(AgentOutput):
    invariants: tuple[RuleDraft, ...]


class WorldClosureReferenceTerm(AgentOutput):
    kind: Literal["reference"]
    source: RuleValueSource
    pointer: str
    value_type: RuleValueType


class WorldClosureConstantTerm(AgentOutput):
    kind: Literal["constant"]
    value_type: Literal["null", "boolean", "number", "string", "array", "object"]
    value: JsonValue


class WorldClosureLookupTerm(AgentOutput):
    kind: Literal["lookup_by_key"]
    source: Literal["pre_state", "post_state"]
    collection_pointer: str
    key_field: Identifier
    key: WorldClosureReferenceTerm | WorldClosureConstantTerm
    value_pointer: str
    value_type: RuleValueType


class WorldClosureArithmeticTerm(AgentOutput):
    kind: Literal["arithmetic"]
    operator: Literal["add", "subtract", "multiply", "divide", "modulo"]
    left: WorldClosureReferenceTerm | WorldClosureConstantTerm | WorldClosureLookupTerm
    right: WorldClosureReferenceTerm | WorldClosureConstantTerm | WorldClosureLookupTerm


WorldClosureTerm = Annotated[
    WorldClosureReferenceTerm
    | WorldClosureConstantTerm
    | WorldClosureLookupTerm
    | WorldClosureArithmeticTerm,
    Field(discriminator="kind"),
]


class WorldClosureConstraint(AgentOutput):
    """One deduplicated executable relation; clause identity metadata is intentionally absent."""

    constraint_id: Identifier
    left: WorldClosureTerm
    operator: Literal[
        "exists",
        "not_exists",
        "equal",
        "not_equal",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "contains",
        "not_contains",
        "schema_valid",
    ]
    right: WorldClosureTerm | None = None
    negate: bool = False
    schema_elided: bool = False


class WorldClosureRulePath(AgentOutput):
    """Rule intent plus references into the deduplicated constraint catalog."""

    rule_id: Identifier
    description: Annotated[str, Field(min_length=1)]
    boolean_operator: Literal["all", "any"]
    constraint_ids: tuple[Identifier, ...] = ()
    evidence_claim_ids: tuple[Identifier, ...] = ()


class WorldClosureErrorPath(AgentOutput):
    """Only the error information that can affect cross-tool world invariants."""

    error_code: Identifier
    when: WorldClosureRulePath
    state_effect: Literal["none", "partial", "rolled_back", "unknown"]


class WorldClosureToolPath(AgentOutput):
    """Compact successful and failed state paths for one frozen tool."""

    tool_id: Identifier
    preconditions: tuple[WorldClosureRulePath, ...] = ()
    transition: tuple[WorldClosureRulePath, ...] = ()
    postconditions: tuple[WorldClosureRulePath, ...] = ()
    errors: tuple[WorldClosureErrorPath, ...] = ()


class WorldClosureContext(AgentOutput):
    """Framework-derived bounded input for authoring global invariant Rules."""

    core_invariants: Annotated[tuple[str, ...], Field(min_length=1)]
    root_state_schema: dict[str, JsonValue]
    constraints: tuple[WorldClosureConstraint, ...] = ()
    initial_state_rules: tuple[WorldClosureRulePath, ...] = ()
    tool_paths: Annotated[tuple[WorldClosureToolPath, ...], Field(min_length=1)]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    evidence_claims: tuple[Claim, ...] = ()

    @model_validator(mode="after")
    def validate_constraint_catalog(self) -> WorldClosureContext:
        constraint_ids = [item.constraint_id for item in self.constraints]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise PydanticCustomError(
                "world_closure_constraint_id_duplicate",
                "world closure constraint ids must be unique",
            )
        known = set(constraint_ids)
        rules = list(self.initial_state_rules)
        for tool in self.tool_paths:
            rules.extend(tool.preconditions)
            rules.extend(tool.transition)
            rules.extend(tool.postconditions)
            rules.extend(error.when for error in tool.errors)
        referenced = {item for rule in rules for item in rule.constraint_ids}
        # The unknown/unreachable identifiers are Agent-supplied values, so they
        # stay out of the diagnostic: the stable code plus the field path is what
        # makes this repairable without echoing rejected input.
        if referenced - known:
            raise PydanticCustomError(
                "world_closure_constraint_reference_unknown",
                "world closure rules must reference only catalogued constraint ids",
            )
        if known - referenced:
            raise PydanticCustomError(
                "world_closure_constraint_unreachable",
                "every world closure catalog constraint must be referenced by a rule",
            )
        return self


class TrainingRuleCatalogEntry(AgentOutput):
    """Stable identity and intent of one already-validated world Rule."""

    rule_id: Identifier
    family: Literal[
        "initial_state",
        "invariant",
        "precondition",
        "transition",
        "postcondition",
        "error_condition",
        "permission",
        "task_success",
        "task_failure",
        "task_terminal",
        "sampling",
    ]
    description: Annotated[str, Field(min_length=1)]
    evidence_claim_ids: tuple[Identifier, ...] = ()


class TrainingToolContext(AgentOutput):
    """Task-authoring view of one executable tool without operational payload."""

    tool_id: Identifier
    description: Annotated[str, Field(min_length=1)]
    input_schema: dict[str, JsonValue]
    allowed_actor_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rules: Annotated[tuple[TrainingRuleCatalogEntry, ...], Field(min_length=1)]
    error_codes: tuple[Identifier, ...] = ()
    evidence_claim_ids: tuple[Identifier, ...] = ()


class TrainingContractContext(AgentOutput):
    """Framework-derived bounded input for task, reward, and verifier policy."""

    boundary: WorldBoundary
    root_state_schema: dict[str, JsonValue]
    initial_state_constraints: tuple[Rule, ...] = ()
    tools: Annotated[tuple[TrainingToolContext, ...], Field(min_length=1)]
    world_invariants: tuple[TrainingRuleCatalogEntry, ...]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]
    evidence_claims: tuple[Claim, ...] = ()


class CurriculumContractDraft(AgentOutput):
    """Agent-authored task distribution; framework compiles reward and verification."""

    coverage_dimensions: Annotated[tuple[CoverageDimension, ...], Field(min_length=1)]
    curriculum: CurriculumRequirements
    unresolved_questions: tuple[str, ...] = ()


class CurriculumTaskPlan(AgentOutput):
    """Frozen lightweight identity and reachability boundary for one task shard."""

    task_type: Identifier
    objective: Annotated[str, Field(min_length=1)]
    allowed_actor_ids: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=MAX_ACTORS_PER_TASK),
    ]
    required_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    difficulty_dimensions: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=MAX_DIFFICULTY_DIMENSIONS),
    ]
    minimum_tool_calls: Annotated[int, Field(ge=1, le=32)] = 1

    @model_validator(mode="after")
    def validate_unique_sets(self) -> CurriculumTaskPlan:
        for label, values in (
            ("allowed_actor_ids", self.allowed_actor_ids),
            ("required_tool_ids", self.required_tool_ids),
            ("difficulty_dimensions", self.difficulty_dimensions),
        ):
            if len(set(values)) != len(values):
                # ``label`` is a framework literal from the tuple above; the
                # Agent-supplied task_type stays out of the code and message and
                # is already identified by the validated field path.
                raise PydanticCustomError(
                    f"task_plan_{label}_duplicate",
                    "task plan values must be unique within this field",
                )
        return self


class CurriculumPlanDraft(AgentOutput):
    """Bounded curriculum topology before independently authored task contracts."""

    coverage_dimensions: Annotated[
        tuple[CoverageDimension, ...], Field(min_length=1, max_length=32)
    ]
    task_plans: Annotated[tuple[CurriculumTaskPlan, ...], Field(min_length=1, max_length=8)]
    difficulty_dimensions: Annotated[
        tuple[DifficultyDimension, ...], Field(min_length=1, max_length=32)
    ]
    generation_seed_space: Annotated[str, Field(min_length=1)]
    minimum_distinct_initial_states: Annotated[
        int, Field(ge=2, le=MAX_DISTINCT_CURRICULUM_SAMPLES)
    ] = 2
    minimum_distinct_tasks_per_type: Annotated[
        int, Field(ge=2, le=MAX_DISTINCT_CURRICULUM_SAMPLES)
    ] = 2
    sampling_constraints: Annotated[tuple[Rule, ...], Field(max_length=128)] = ()
    unresolved_questions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_plan_topology(self) -> CurriculumPlanDraft:
        task_ids = [item.task_type for item in self.task_plans]
        if len(set(task_ids)) != len(task_ids):
            raise PydanticCustomError(
                "curriculum_task_plan_id_duplicate",
                "curriculum task plan ids must be unique",
            )
        dimensions = [item.dimension for item in self.difficulty_dimensions]
        if len(set(dimensions)) != len(dimensions):
            raise PydanticCustomError(
                "curriculum_difficulty_dimension_duplicate",
                "curriculum difficulty dimensions must be unique",
            )
        dimension_set = set(dimensions)
        for task in self.task_plans:
            if not set(task.difficulty_dimensions) <= dimension_set:
                raise PydanticCustomError(
                    "curriculum_task_difficulty_dimension_unknown",
                    "task plans must reference declared curriculum difficulty dimensions",
                )
        coverage = [item.dimension for item in self.coverage_dimensions]
        if len(set(coverage)) != len(coverage):
            raise PydanticCustomError(
                "curriculum_coverage_dimension_duplicate",
                "curriculum coverage dimensions must be unique",
            )
        return self


class CurriculumTaskPlanSourceDraft(AgentOutput):
    task_type: Identifier
    objective: Annotated[str, Field(min_length=1)]
    allowed_actor_ids: Annotated[
        tuple[Identifier, ...],
        Field(
            min_length=1,
            max_length=MAX_ACTORS_PER_TASK,
            description=(
                "Alternative task callers, not a roster of every workflow participant. "
                "Every listed actor must independently be permitted to invoke every "
                "required_tool_id."
            ),
        ),
    ]
    required_tool_ids: Annotated[
        tuple[Identifier, ...],
        Field(
            min_length=1,
            description=(
                "Tools the eligible task caller must invoke. Do not list verifier-only "
                "tools or calls made solely by a different workflow participant."
            ),
        ),
    ]
    difficulty_dimensions: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=MAX_DIFFICULTY_DIMENSIONS),
    ]
    minimum_tool_calls: Annotated[int, Field(ge=1, le=32)] = 1


class CurriculumPlanSourceDraft(AgentOutput):
    """Agent-facing curriculum topology and sampling Rule source."""

    coverage_dimensions: Annotated[
        tuple[CoverageDimension, ...], Field(min_length=1, max_length=32)
    ]
    task_plans: Annotated[
        tuple[CurriculumTaskPlanSourceDraft, ...], Field(min_length=1, max_length=8)
    ]
    difficulty_dimensions: Annotated[
        tuple[DifficultyDimension, ...], Field(min_length=1, max_length=32)
    ]
    generation_seed_space: Annotated[str, Field(min_length=1)]
    minimum_distinct_initial_states: Annotated[
        int, Field(ge=2, le=MAX_DISTINCT_CURRICULUM_SAMPLES)
    ] = 2
    minimum_distinct_tasks_per_type: Annotated[
        int, Field(ge=2, le=MAX_DISTINCT_CURRICULUM_SAMPLES)
    ] = 2
    sampling_constraints: Annotated[tuple[RuleDraft, ...], Field(max_length=128)] = ()
    unresolved_questions: tuple[str, ...] = ()


class TaskRequirementDraft(AgentOutput):
    """Open task semantics before framework-owned schema compilation.

    The Agent authors objectives and executable Rule IR.  It deliberately does
    not author JSON Schema envelopes, evaluator bindings, or reachability
    budgets: those are protocol and release-policy concerns compiled by the
    framework from the frozen world and the task-goal references below.
    """

    task_type: Identifier
    objective: Annotated[str, Field(min_length=1)]
    allowed_actor_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    required_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    initial_state_constraints: tuple[Rule, ...] = ()
    success_conditions: Annotated[tuple[Rule, ...], Field(min_length=1, max_length=64)]
    failure_conditions: Annotated[tuple[Rule, ...], Field(max_length=64)] = ()
    terminal_conditions: Annotated[tuple[Rule, ...], Field(min_length=1, max_length=64)]
    difficulty_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    minimum_tool_calls: Annotated[int, Field(ge=1, le=32)] = 1


class TaskRequirementSourceDraft(AgentOutput):
    """Agent-facing task semantics compiled into framework-owned task protocols."""

    task_type: Identifier
    objective: Annotated[str, Field(min_length=1)]
    allowed_actor_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    required_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    initial_state_constraints: tuple[RuleDraft, ...] = ()
    success_conditions: Annotated[tuple[RuleDraft, ...], Field(min_length=1, max_length=64)]
    failure_conditions: Annotated[tuple[RuleDraft, ...], Field(max_length=64)] = ()
    terminal_conditions: Annotated[tuple[RuleDraft, ...], Field(min_length=1, max_length=64)]
    difficulty_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    minimum_tool_calls: Annotated[int, Field(ge=1, le=32)] = 1


class WorldModelDraft(AgentOutput):
    """Executable-world semantics, intentionally independent of training policy."""

    boundary: WorldBoundary
    state: StateSchema
    tools: Annotated[tuple[ToolContract, ...], Field(min_length=1)]
    invariants: tuple[Rule, ...]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]


class TrainingContractDraft(AgentOutput):
    """Task/reward/evaluation semantics compiled against one frozen world model."""

    coverage_dimensions: Annotated[tuple[CoverageDimension, ...], Field(min_length=1)]
    curriculum: CurriculumRequirements
    reward: RewardSpec
    verification: VerificationRequirements
    unresolved_questions: tuple[str, ...] = ()


class EnvironmentDesignDraft(WorldModelDraft, TrainingContractDraft):
    """Framework-composed complete design validated across both semantic halves."""


class WorldSemanticSourceIRDraft(AgentOutput):
    """Typed source compiled into a complete executable WorldModelDraft.

    State and Tool JSON Schemas are absent by construction.  The Agent owns
    bounded semantic node graphs; framework code owns every schema envelope,
    root reference, closure check, and ToolSurface assembly.
    """

    boundary: WorldBoundaryDraft
    state_inventory: StateEntityInventoryDraft
    state_entity_schemas: Annotated[
        tuple[StateEntitySchemaIRDraft, ...], Field(min_length=1, max_length=12)
    ]
    initial_state_rules: InitialStateRulesDraft
    tool_inventory: WorldToolPlanInventoryDraft
    tool_schemas: Annotated[tuple[ToolSchemaIRDraft, ...], Field(min_length=3, max_length=24)]
    tool_semantics: Annotated[tuple[ToolSemanticsDraft, ...], Field(min_length=1, max_length=8)]
    closure: WorldClosureDraft

    @model_validator(mode="after")
    def validate_topology(self) -> WorldSemanticSourceIRDraft:
        planned_entities = tuple(item.entity for item in self.state_inventory.entities)
        authored_entities = tuple(item.entity for item in self.state_entity_schemas)
        if authored_entities != planned_entities:
            raise PydanticCustomError(
                "state_schema_shard_inventory_mismatch",
                "state schema IR shards must preserve state inventory order and identity",
            )
        planned_tools = tuple(item.tool_id for item in self.tool_inventory.tools)
        authored_semantics = tuple(item.tool_id for item in self.tool_semantics)
        if authored_semantics != planned_tools:
            raise PydanticCustomError(
                "tool_semantics_inventory_mismatch",
                "tool semantics must preserve tool inventory order and identity",
            )
        expected_schema_shards = tuple(
            (tool_id, schema_kind)
            for tool_id in planned_tools
            for schema_kind in ("input", "output", "observation")
        )
        actual_schema_shards = tuple((item.tool_id, item.schema_kind) for item in self.tool_schemas)
        if actual_schema_shards != expected_schema_shards:
            raise PydanticCustomError(
                "tool_schema_shard_order_mismatch",
                "tool schema IR shards must be ordered input/output/observation for every tool",
            )
        return self


class StateFieldSourceDraft(CompactFieldSemanticDraft):
    """One state field declared once; framework derives plan and schema identity."""

    role: Literal["primary_key", "mutable"]
    lifecycle: bool = False

    @model_validator(mode="after")
    def validate_lifecycle_semantics(self) -> StateFieldSourceDraft:
        if self.lifecycle and (
            self.role != "mutable" or self.value_type != "string" or not self.enum_values
        ):
            raise PydanticCustomError(
                "state_field_lifecycle_contract",
                "lifecycle requires mutable string field with non-empty enum_values",
            )
        return self


class StateEntitySourceDraft(AgentOutput):
    """Single Agent-owned source for state, resource ownership and visibility.

    Boundary resources and actor-visible root fields are compiled from these
    declarations.  They are deliberately not repeated in the boundary source.
    """

    entity: Identifier
    purpose: Annotated[str, Field(min_length=1)]
    root_field: Identifier
    storage: Literal["collection", "singleton"]
    system_of_record: Identifier
    owned_resource_ids: tuple[Identifier, ...] = ()
    visible_to_actor_ids: tuple[Identifier, ...] = ()
    fields: Annotated[tuple[StateFieldSourceDraft, ...], Field(min_length=1, max_length=32)]
    evidence_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_owned_sets(self) -> StateEntitySourceDraft:
        if len(set(self.owned_resource_ids)) != len(self.owned_resource_ids):
            raise PydanticCustomError(
                "state_entity_owned_resource_duplicate",
                "state entity owned resources must be unique",
            )
        if len(set(self.visible_to_actor_ids)) != len(self.visible_to_actor_ids):
            raise PydanticCustomError(
                "state_entity_visible_actor_duplicate",
                "state entity visible actor ids must be unique",
            )
        return self


class ActorAuthoritySourceDraft(AgentOutput):
    """Actor identity and authority; state visibility is entity-owned."""

    actor: Identifier
    authorities: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_authorities(self) -> ActorAuthoritySourceDraft:
        if len(set(self.authorities)) != len(self.authorities):
            raise PydanticCustomError(
                "actor_authority_duplicate",
                "actor authorities must be unique",
            )
        return self


class WorldBoundarySourceDraft(AgentOutput):
    """Boundary meaning without duplicated resource or visibility indexes."""

    primary_domain: Identifier
    actors_and_authority: Annotated[tuple[ActorAuthoritySourceDraft, ...], Field(min_length=1)]
    systems_of_record: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    transition_authorities: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    tool_namespaces: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    core_invariants: Annotated[tuple[str, ...], Field(min_length=1)]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_boundary_sets(self) -> WorldBoundarySourceDraft:
        actors = tuple(item.actor for item in self.actors_and_authority)
        if len(set(actors)) != len(actors):
            raise PydanticCustomError(
                "boundary_actor_id_duplicate",
                "boundary actor ids must be unique",
            )
        for label, values in (
            ("systems_of_record", self.systems_of_record),
            ("transition_authorities", self.transition_authorities),
            ("tool_namespaces", self.tool_namespaces),
            ("core_invariants", self.core_invariants),
            ("task_dimensions", self.task_dimensions),
        ):
            if len(set(values)) != len(values):
                # ``label`` is a framework literal from the tuple above.
                raise PydanticCustomError(
                    f"boundary_{label}_duplicate",
                    "boundary source values must be unique within this field",
                )
        return self


class StateEntityFieldsSourceDraft(AgentOutput):
    entity: Identifier
    fields: Annotated[tuple[CompactFieldSemanticDraft, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def validate_unique_fields(self) -> StateEntityFieldsSourceDraft:
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise PydanticCustomError(
                "state_entity_field_name_duplicate",
                "state entity field names must be unique",
            )
        return self


class WorldArchitectureSourceDraft(AgentOutput):
    """One coherent architecture transaction before tool behavior is authored.

    The Agent owns field and resource meaning, but not schema node ids, graph
    edges, nullable wrappers or JSON Schema syntax.  The framework compiles all
    of those mechanically, so cardinality increases output data rather than
    Agent turns or reasoning surface.
    """

    boundary: WorldBoundarySourceDraft
    state_entities: Annotated[
        tuple[StateEntitySourceDraft, ...], Field(min_length=1, max_length=12)
    ]
    tool_inventory: WorldToolSourceInventoryDraft


class ToolCouplingGroupPlan(V2Contract):
    group_id: Identifier
    ordered_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    shared_state_entity_ids: tuple[Identifier, ...] = ()
    namespaces: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    coupling_reasons: Annotated[
        tuple[Literal["namespace", "state_overlap"], ...], Field(min_length=1)
    ]
    mode: Literal["single_batch", "multi_batch"]
    # Captured historical plans may contain wider groups.  They remain
    # read-only diagnostic inputs: ``derive_final_design_definitions`` rejects
    # every non-singleton physical batch before a new graph can execute or
    # release.  Keep this decoder ceiling only so a project Agent can inspect
    # the captured topology without treating it as a new execution plan.
    batches: Annotated[
        tuple[
            Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=4)],
            ...,
        ],
        Field(min_length=1, max_length=MAX_SEMANTICS_BATCHES),
    ]

    @model_validator(mode="after")
    def validate_batches(self) -> ToolCouplingGroupPlan:
        flattened = tuple(tool_id for batch in self.batches for tool_id in batch)
        if flattened != self.ordered_tool_ids:
            raise PydanticCustomError(
                "coupling_batch_group_order_mismatch",
                "coupling batches must preserve exact group tool order and identity",
            )
        if self.mode == "single_batch" and len(self.batches) != 1:
            raise PydanticCustomError(
                "coupling_single_batch_arity",
                "single_batch coupling group requires exactly one batch",
            )
        if self.mode == "multi_batch" and len(self.batches) < 2:
            raise PydanticCustomError(
                "coupling_multi_batch_arity",
                "multi_batch coupling group requires at least two batches",
            )
        return self


class ToolCouplingPlan(V2Contract):
    plan_id: Identifier
    architecture_ref: ArtifactRef
    groups: Annotated[tuple[ToolCouplingGroupPlan, ...], Field(min_length=1, max_length=8)]
    # See ``ToolCouplingGroupPlan.batches``: new plans are mechanically
    # singleton shards, while this wider decoder is needed only to inspect a
    # captured ancestor closure in diagnostic mode.
    execution_batches: Annotated[
        tuple[
            Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=4)],
            ...,
        ],
        Field(min_length=1, max_length=MAX_SEMANTICS_BATCHES),
    ]

    @model_validator(mode="after")
    def validate_unique_membership(self) -> ToolCouplingPlan:
        group_ids = tuple(group.group_id for group in self.groups)
        tool_ids = tuple(tool_id for group in self.groups for tool_id in group.ordered_tool_ids)
        if len(set(group_ids)) != len(group_ids):
            raise PydanticCustomError(
                "coupling_group_id_duplicate",
                "tool coupling group ids must be unique",
            )
        if len(set(tool_ids)) != len(tool_ids):
            raise PydanticCustomError(
                "coupling_tool_group_membership_duplicate",
                "each tool must belong to exactly one coupling group",
            )
        scheduled = tuple(tool_id for batch in self.execution_batches for tool_id in batch)
        if set(scheduled) != set(tool_ids) or len(scheduled) != len(tool_ids):
            raise PydanticCustomError(
                "coupling_execution_batch_coverage",
                "execution batches must schedule every coupling-plan tool exactly once",
            )
        return self


class SharedAtomicityDomainSourceDraft(AgentOutput):
    domain_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    atomicity: Literal["atomic", "best_effort", "saga", "none"]
    rationale: Annotated[str, Field(min_length=1)]


class SharedConcurrencyDomainSourceDraft(AgentOutput):
    domain_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    isolation: Literal[
        "serial",
        "serializable",
        "snapshot",
        "read_committed",
        "optimistic",
        "last_write_wins",
    ]
    rationale: Annotated[str, Field(min_length=1)]


class SharedIdempotencyDomainSourceDraft(AgentOutput):
    domain_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    mode: IdempotencyMode
    rationale: Annotated[str, Field(min_length=1)]


class SharedOrderingConstraintSourceDraft(AgentOutput):
    before_tool_id: Identifier
    after_tool_id: Identifier
    rationale: Annotated[str, Field(min_length=1)]
    evidence_claim_ids: tuple[Identifier, ...] = ()


class SharedCompensationEdgeSourceDraft(AgentOutput):
    failure_tool_id: Identifier
    compensation_tool_id: Identifier
    rationale: Annotated[str, Field(min_length=1)]


class SharedErrorPolicySourceDraft(AgentOutput):
    policy_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    required_error_suffix: Annotated[
        Identifier,
        Field(
            description=(
                "Required final Identifier segment of a matching tool error code. "
                "Any Identifier separator '.', ':', '_', or '-' may precede the segment."
            )
        ),
    ]
    retryable: bool
    rationale: Annotated[str, Field(min_length=1)]


class SharedToolSemanticsSourceDraft(AgentOutput):
    atomicity_domains: Annotated[
        tuple[SharedAtomicityDomainSourceDraft, ...], Field(min_length=1, max_length=8)
    ]
    concurrency_domains: Annotated[
        tuple[SharedConcurrencyDomainSourceDraft, ...], Field(min_length=1, max_length=8)
    ]
    idempotency_domains: Annotated[
        tuple[SharedIdempotencyDomainSourceDraft, ...], Field(min_length=1, max_length=8)
    ]
    ordering_constraints: Annotated[
        tuple[SharedOrderingConstraintSourceDraft, ...], Field(max_length=16)
    ] = ()
    compensation_edges: Annotated[
        tuple[SharedCompensationEdgeSourceDraft, ...], Field(max_length=16)
    ] = ()
    error_policies: Annotated[
        tuple[SharedErrorPolicySourceDraft, ...], Field(min_length=1, max_length=16)
    ]


class SharedToolSemanticsContract(V2Contract):
    contract_id: Identifier
    group_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=2, max_length=8)]
    source: SharedToolSemanticsSourceDraft


class ToolSemanticGroupClosure(V2Contract):
    closure_id: Identifier
    group_id: Identifier
    member_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]
    semantic_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1, max_length=8)]
    shared_contract_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_member_refs(self) -> ToolSemanticGroupClosure:
        if len(self.semantic_refs) != len(self.member_tool_ids):
            raise PydanticCustomError(
                "group_closure_semantic_ref_arity",
                "group closure requires one semantic ref per member tool",
            )
        return self


class WorldRuleSemanticsSourceDraft(AgentOutput):
    """Executable reset/global rules authored only after schema closure exists."""

    initial_state_rules: InitialStateRulesSourceDraft
    invariants: Annotated[tuple[RuleDraft, ...], Field(max_length=64)]


class ToolRuleConditionsSourceDraft(AgentOutput):
    tool_id: Identifier
    preconditions: tuple[ToolRuleDraft, ...] = ()
    postconditions: tuple[ToolRuleDraft, ...] = ()


class ToolRuleStateTransitionSourceDraft(AgentOutput):
    tool_id: Identifier
    transition: Annotated[tuple[ToolRuleDraft, ...], Field(min_length=1)]


class ToolRuleErrorSourceDraft(AgentOutput):
    error_code: Identifier
    when: ToolRuleDraft
    observation: Annotated[str, Field(min_length=1)]
    state_effect: Literal["none", "partial", "rolled_back", "unknown"]
    retryable: bool
    evidence_claim_ids: tuple[Identifier, ...] = ()


class ToolRuleErrorsSourceDraft(AgentOutput):
    tool_id: Identifier
    errors: Annotated[tuple[ToolRuleErrorSourceDraft, ...], Field(min_length=1)]


class ToolRulePermissionSourceDraft(AgentOutput):
    permission_id: Identifier
    required_scopes_by_actor: Annotated[
        dict[Identifier, tuple[Identifier, ...]], Field(min_length=1)
    ]
    condition: ToolRuleDraft | None = None
    denied_observation: Annotated[str, Field(min_length=1)]


class ToolRuleAccessObservationSourceDraft(AgentOutput):
    tool_id: Identifier
    permission: ToolRulePermissionSourceDraft
    observation: ObservationSemanticsSourceDraft


class ToolSemanticSourceDraft(AgentOutput):
    """All business semantics for one frozen tool in one transaction batch."""

    tool_id: Identifier
    conditions: ToolRuleConditionsSourceDraft
    state_transition: ToolRuleStateTransitionSourceDraft
    errors: ToolRuleErrorsSourceDraft
    access_observation: ToolRuleAccessObservationSourceDraft
    reliability: ToolReliabilitySourceDraft

    @model_validator(mode="after")
    def derive_rule_families(self) -> ToolSemanticSourceDraft:
        """Own section-derived Rule families in framework code.

        A rule's family is already determined by its one closed containment
        path in this ToolSemantics wire object. Asking the Agent to repeat it
        caused format-only semantic failures such as a postcondition label in
        ``state_transition.transition``. Normalize both omission and an
        incorrect redundant label before the general Rule compiler sees the
        draft; the compiler still validates all Agent-authored rule content.
        """

        conditions = self.conditions.model_copy(
            update={
                "preconditions": tuple(
                    _with_tool_rule_family(rule, "precondition")
                    for rule in self.conditions.preconditions
                ),
                "postconditions": tuple(
                    _with_tool_rule_family(rule, "postcondition")
                    for rule in self.conditions.postconditions
                ),
            }
        )
        state_transition = self.state_transition.model_copy(
            update={
                "transition": tuple(
                    _with_tool_rule_family(rule, "transition")
                    for rule in self.state_transition.transition
                )
            }
        )
        errors = self.errors.model_copy(
            update={
                "errors": tuple(
                    error.model_copy(
                        update={"when": _with_tool_rule_family(error.when, "error_condition")}
                    )
                    for error in self.errors.errors
                )
            }
        )
        permission = self.access_observation.permission
        access_observation = self.access_observation.model_copy(
            update={
                "permission": permission.model_copy(
                    update={
                        "condition": (
                            _with_tool_rule_family(permission.condition, "permission")
                            if permission.condition is not None
                            else None
                        )
                    }
                )
            }
        )
        return self.model_copy(
            update={
                "conditions": conditions,
                "state_transition": state_transition,
                "errors": errors,
                "access_observation": access_observation,
            }
        )


class ToolSemanticsBatchSourceDraft(AgentOutput):
    """One complete physical ToolSemantics shard for one frozen tool."""

    tools: Annotated[
        tuple[ToolSemanticSourceDraft, ...],
        Field(min_length=1, max_length=MAX_TOOLS_PER_SEMANTICS_BATCH),
    ]

    @model_validator(mode="after")
    def validate_unique_tools(self) -> ToolSemanticsBatchSourceDraft:
        tool_ids = tuple(item.tool_id for item in self.tools)
        if len(set(tool_ids)) != len(tool_ids):
            raise PydanticCustomError(
                "tool_semantics_batch_tool_id_duplicate",
                "tool semantics batch tool ids must be unique",
            )
        return self


class MaterializedToolSemanticSource(BaseModel):
    """Framework-expanded ToolSemantics source accepted by the Rule compiler."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_id: Identifier
    conditions: ToolConditionsSourceDraft
    state_transition: ToolStateTransitionSourceDraft
    errors: ToolErrorsSourceDraft
    access_observation: ToolAccessObservationSourceDraft
    reliability: ToolReliabilitySourceDraft


class MaterializedToolSemanticsBatch(BaseModel):
    """Non-durable compiler input derived from one closed Agent wire draft."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tools: Annotated[
        tuple[MaterializedToolSemanticSource, ...],
        Field(min_length=1, max_length=MAX_TOOLS_PER_SEMANTICS_BATCH),
    ]


class TrainingSemanticSourceDraft(AgentOutput):
    """Curriculum and task meaning after the executable world has been frozen."""

    curriculum_plan: CurriculumPlanSourceDraft
    task_requirements: Annotated[
        tuple[TaskRequirementSourceDraft, ...], Field(min_length=1, max_length=8)
    ]

    @model_validator(mode="after")
    def validate_task_topology(self) -> TrainingSemanticSourceDraft:
        planned = tuple(item.task_type for item in self.curriculum_plan.task_plans)
        authored = tuple(item.task_type for item in self.task_requirements)
        if authored != planned:
            raise PydanticCustomError(
                "training_task_requirement_plan_mismatch",
                "task requirements must preserve curriculum plan order and identity",
            )
        return self


class EnvironmentSemanticSourceDraft(AgentOutput):
    """Agent-owned semantic source for canonical framework compilation.

    A repair or expansion Agent may change the executable world, curriculum
    topology, and task Rule IR.  It cannot author task protocol schemas,
    evaluator bindings, reward values, or verification closure; those fields
    exist only on the compiled :class:`EnvironmentDesignDraft`.
    """

    world: WorldSemanticSourceIRDraft
    curriculum_plan: CurriculumPlanDraft
    task_requirements: Annotated[
        tuple[TaskRequirementDraft, ...], Field(min_length=1, max_length=8)
    ]

    @model_validator(mode="after")
    def validate_task_topology(self) -> EnvironmentSemanticSourceDraft:
        planned = tuple(item.task_type for item in self.curriculum_plan.task_plans)
        authored = tuple(item.task_type for item in self.task_requirements)
        if authored != planned:
            raise PydanticCustomError(
                "environment_task_requirement_plan_mismatch",
                "semantic source task requirements must preserve curriculum plan "
                "order and identity",
            )
        return self


class ToolSurfaceDeltaClaimDraft(AgentOutput):
    operation: Literal["add", "remove", "modify"]
    tool_id: Identifier
    before_hash: ContentHash | None = None
    changed_aspects: Annotated[
        tuple[Literal["surface", "schema", "observation_schema"], ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_operation(self) -> ToolSurfaceDeltaClaimDraft:
        if (self.operation == "add") != (self.before_hash is None):
            raise PydanticCustomError(
                "tool_surface_delta_before_hash_binding",
                "add forbids before_hash; remove/modify require it",
            )
        return self


class ToolSemanticsDeltaClaimDraft(AgentOutput):
    operation: Literal["add", "remove", "modify"]
    tool_id: Identifier
    before_hash: ContentHash | None = None
    changed_aspects: Annotated[
        tuple[
            Literal[
                "precondition",
                "transition",
                "postcondition",
                "error",
                "permission",
                "observation",
                "idempotency",
                "retry",
                "timeout",
                "transaction",
                "rollback",
                "concurrency",
            ],
            ...,
        ],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_operation(self) -> ToolSemanticsDeltaClaimDraft:
        if (self.operation == "add") != (self.before_hash is None):
            raise PydanticCustomError(
                "tool_semantics_delta_before_hash_binding",
                "add forbids before_hash; remove/modify require it",
            )
        return self


class StateSchemaDeltaClaimDraft(AgentOutput):
    before_hash: ContentHash
    changed_entities: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: Annotated[str, Field(min_length=1)]


class TransitionConstraintDeltaClaimDraft(AgentOutput):
    operation: Literal["add", "remove", "modify"]
    rule_id: Identifier
    before_hash: ContentHash | None = None
    affected_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_operation(self) -> TransitionConstraintDeltaClaimDraft:
        if (self.operation == "add") != (self.before_hash is None):
            raise PydanticCustomError(
                "transition_constraint_delta_before_hash_binding",
                "add forbids before_hash; remove/modify require it",
            )
        return self


class TaskScopeDeltaClaimDraft(AgentOutput):
    operation: Literal["add", "remove", "modify"]
    task_type: Identifier
    before_hash: ContentHash | None = None
    rationale: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_operation(self) -> TaskScopeDeltaClaimDraft:
        if (self.operation == "add") != (self.before_hash is None):
            raise PydanticCustomError(
                "task_scope_delta_before_hash_binding",
                "add forbids before_hash; remove/modify require it",
            )
        return self


class TaskDistributionDeltaClaimDraft(AgentOutput):
    """Agent claim for sampling semantics; framework supplies the after snapshot."""

    before_hash: ContentHash
    changed_aspects: Annotated[
        tuple[
            Literal[
                "task_type_order",
                "task_dimensions",
                "difficulty_dimensions",
                "generation_seed_space",
                "minimum_distinct_initial_states",
                "minimum_distinct_tasks_per_type",
                "sampling_constraints",
            ],
            ...,
        ],
        Field(min_length=1),
    ]
    rationale: Annotated[str, Field(min_length=1)]


class WorldBoundaryDeltaClaimDraft(AgentOutput):
    before_hash: ContentHash
    changed_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: Annotated[str, Field(min_length=1)]


class ExpansionSemanticDeltaDraft(AgentOutput):
    """Agent-declared change claim; framework owns every authoritative after value."""

    tool_surface_deltas: tuple[ToolSurfaceDeltaClaimDraft, ...] = ()
    tool_semantics_deltas: tuple[ToolSemanticsDeltaClaimDraft, ...] = ()
    state_schema_deltas: tuple[StateSchemaDeltaClaimDraft, ...] = ()
    transition_constraint_deltas: tuple[TransitionConstraintDeltaClaimDraft, ...] = ()
    task_scope_deltas: tuple[TaskScopeDeltaClaimDraft, ...] = ()
    task_distribution_deltas: Annotated[
        tuple[TaskDistributionDeltaClaimDraft, ...], Field(max_length=1)
    ] = ()
    world_boundary_delta: WorldBoundaryDeltaClaimDraft | None = None
    unresolved_questions: tuple[str, ...] = ()


class ExpansionDesignDraft(AgentOutput):
    """Agent-owned expansion semantics plus a framework-checkable delta claim."""

    semantic_source: EnvironmentSemanticSourceDraft
    semantic_delta: ExpansionSemanticDeltaDraft


class DiscoveryClueDraft(AgentOutput):
    hypothesis: Annotated[str, Field(min_length=1)]
    evidence_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    tool_or_workflow_surface: tuple[str, ...] = ()
    coverage_dimensions: Annotated[tuple[str, ...], Field(min_length=1)]
    scope_relation: Literal["in_scope", "adjacent", "new_domain", "uncertain"]
    feasibility: Literal["supported", "plausible", "uncertain", "blocked"]
    risk: Literal["low", "medium", "high", "critical"]
    unresolved_questions: tuple[str, ...] = ()


class DiscoverySynthesis(AgentOutput):
    clues: tuple[DiscoveryClueDraft, ...] = ()


class ExpansionSourceHypothesisDraft(AgentOutput):
    statement: Annotated[str, Field(min_length=1)]
    tool_or_workflow_surface: tuple[str, ...] = ()
    coverage_dimensions: Annotated[tuple[str, ...], Field(min_length=1)]


class ExpansionSourcePlan(AgentOutput):
    hypotheses: Annotated[
        tuple[ExpansionSourceHypothesisDraft, ...],
        Field(min_length=1, max_length=32),
    ]
    queries: Annotated[tuple[PlannedSearchQuery, ...], Field(min_length=1, max_length=32)]


class ExpansionSourceClueDraft(DiscoveryClueDraft):
    hypothesis_index: Annotated[int, Field(ge=0)]


class ExpansionSourceSynthesis(AgentOutput):
    clues: tuple[ExpansionSourceClueDraft, ...] = ()


class AdmissionAssessment(AgentOutput):
    relation: Literal["in_scope", "adjacent", "new_domain", "unrelated", "uncertain"]
    challenged_claim_ids: tuple[str, ...] = ()
    confidence: Annotated[float, Field(ge=0, le=1)]
    rationale: Annotated[str, Field(min_length=1)]


for _agent_output_root in (
    ActorAuthoritySourceDraft,
    AdmissionAssessment,
    CurriculumPlanDraft,
    CurriculumPlanSourceDraft,
    DiscoverySynthesis,
    EnvironmentSemanticSourceDraft,
    EvidenceAssumptionClosureDraft,
    EvidenceSynthesisSourceDraft,
    ExpansionDesignDraft,
    ExpansionSourcePlan,
    ExpansionSourceSynthesis,
    InitialStateRulesDraft,
    InitialStateRulesSourceDraft,
    CompactFieldSemanticDraft,
    StateEntitySourceDraft,
    StateFieldSourceDraft,
    ResearchPlan,
    StateEntityFieldsSourceDraft,
    StateEntityInventoryDraft,
    StateEntitySchemaIRDraft,
    SharedToolSemanticsSourceDraft,
    TaskDimensionsDraft,
    TaskRequirementSourceDraft,
    ToolAccessObservationDraft,
    ToolAccessObservationSourceDraft,
    ToolConditionsDraft,
    ToolConditionsSourceDraft,
    ToolErrorsDraft,
    ToolErrorsSourceDraft,
    ToolReliabilityDraft,
    ToolReliabilitySourceDraft,
    ToolSchemaDraft,
    ToolSchemaIRDraft,
    ToolStateTransitionDraft,
    ToolStateTransitionSourceDraft,
    ToolSemanticsBatchSourceDraft,
    ToolInterfaceSourceDraft,
    ToolSurfaceSourceDraft,
    WorldBoundaryDraft,
    WorldBoundarySourceDraft,
    WorldArchitectureSourceDraft,
    WorldRuleSemanticsSourceDraft,
    WorldClosureDraft,
    WorldClosureSourceDraft,
    WorldToolPlanInventoryDraft,
    WorldToolSourceInventoryDraft,
    TrainingSemanticSourceDraft,
):
    register_agent_output_contract(
        _agent_output_root,
        authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
    )


__all__ = [
    "ActorAuthoritySourceDraft",
    "AdmissionAssessment",
    "AssumptionResolutionDraft",
    "CurriculumContractDraft",
    "CurriculumPlanDraft",
    "CurriculumPlanSourceDraft",
    "CurriculumTaskPlan",
    "MAX_SEMANTICS_BATCHES",
    "MAX_TOOLS_PER_SEMANTICS_BATCH",
    "CurriculumTaskPlanSourceDraft",
    "DiscoveryClueDraft",
    "DiscoverySynthesis",
    "EnvironmentDesignDraft",
    "EnvironmentSemanticSourceDraft",
    "EvidenceAssumptionClosureDraft",
    "EvidenceClaimSourceDraft",
    "EvidenceConflictSourceDraft",
    "EvidenceSynthesis",
    "EvidenceSynthesisSourceDraft",
    "ExpansionDesignDraft",
    "ExpansionSourceClueDraft",
    "ExpansionSourceHypothesisDraft",
    "ExpansionSourcePlan",
    "ExpansionSourceSynthesis",
    "ExpansionSemanticDeltaDraft",
    "InitialStateRulesDraft",
    "InitialStateRulesSourceDraft",
    "MaterializedToolSemanticSource",
    "MaterializedToolSemanticsBatch",
    "CompactFieldSemanticDraft",
    "StateEntitySourceDraft",
    "IdempotencySourceDraft",
    "PermissionRuleSourceDraft",
    "ObservationSemanticsSourceDraft",
    "PlannedSearchQuery",
    "ResearchAcquisition",
    "ResearchPlan",
    "RuleArithmeticDraft",
    "RuleAtomDraft",
    "RuleBoundLookupByKeyDraft",
    "RuleBoundReferenceDraft",
    "RuleClauseDraft",
    "RuleConstantDraft",
    "RuleLookupByKeyDraft",
    "RuleDraft",
    "RuleReferenceDraft",
    "RuleTermDraft",
    "SchemaArrayNodeDraft",
    "SchemaBooleanNodeDraft",
    "SchemaIntegerNodeDraft",
    "SchemaNodeDraft",
    "SchemaNullNodeDraft",
    "SchemaNumberNodeDraft",
    "SchemaObjectNodeDraft",
    "SchemaPropertyDraft",
    "SchemaStringNodeDraft",
    "SchemaUnionNodeDraft",
    "SharedAtomicityDomainSourceDraft",
    "SharedCompensationEdgeSourceDraft",
    "SharedConcurrencyDomainSourceDraft",
    "SharedErrorPolicySourceDraft",
    "SharedIdempotencyDomainSourceDraft",
    "SharedOrderingConstraintSourceDraft",
    "SharedToolSemanticsContract",
    "SharedToolSemanticsSourceDraft",
    "StateEntityInventoryDraft",
    "StateEntityFieldsSourceDraft",
    "StateFieldSourceDraft",
    "StateEntityPlan",
    "StateEntitySchemaDraft",
    "StateEntitySchemaIRDraft",
    "StateSchemaDeltaClaimDraft",
    "TrainingContractContext",
    "TrainingContractDraft",
    "TrainingRuleCatalogEntry",
    "TrainingToolContext",
    "TaskDimensionsDraft",
    "TaskRequirementDraft",
    "TaskRequirementSourceDraft",
    "TaskDistributionDeltaClaimDraft",
    "TaskScopeDeltaClaimDraft",
    "ToolAccessObservationDraft",
    "ToolAccessObservationSourceDraft",
    "ToolBehaviorDraft",
    "ToolConditionsDraft",
    "ToolConditionsSourceDraft",
    "ToolCouplingGroupPlan",
    "ToolCouplingPlan",
    "ToolErrorsDraft",
    "ToolErrorsSourceDraft",
    "ToolReliabilityDraft",
    "ToolReliabilitySourceDraft",
    "ToolRuleAccessObservationSourceDraft",
    "ToolRuleArithmeticDraft",
    "ToolRuleAtomDraft",
    "ToolRuleBoundLookupByConstantDraft",
    "ToolRuleBoundLookupByReferenceDraft",
    "ToolRuleClauseDraft",
    "ToolRuleConditionsSourceDraft",
    "ToolRuleDraft",
    "ToolRuleErrorsSourceDraft",
    "ToolRuleErrorSourceDraft",
    "ToolRulePermissionSourceDraft",
    "ToolRuleStateTransitionSourceDraft",
    "ToolRuleTermDraft",
    "ToolSemanticsDeltaClaimDraft",
    "ToolSemanticSourceDraft",
    "ToolSemanticGroupClosure",
    "ToolSemanticsBatchSourceDraft",
    "ToolInterfaceSourceDraft",
    "ToolSurfaceSourceDraft",
    "ToolSemanticsDraft",
    "ToolSchemaDraft",
    "ToolSchemaIRDraft",
    "ToolSurfacePlan",
    "ToolSurfaceSchemasDraft",
    "ToolSurfaceDraft",
    "ToolSurfaceDeltaClaimDraft",
    "ToolStateTransitionDraft",
    "ToolStateTransitionSourceDraft",
    "WorldBoundaryDraft",
    "WorldBoundarySourceDraft",
    "WorldBoundaryDeltaClaimDraft",
    "WorldClosureArithmeticTerm",
    "WorldClosureConstantTerm",
    "WorldClosureLookupTerm",
    "WorldClosureConstraint",
    "WorldClosureDraft",
    "WorldClosureSourceDraft",
    "WorldClosureContext",
    "WorldClosureErrorPath",
    "WorldClosureReferenceTerm",
    "WorldClosureRulePath",
    "WorldClosureTerm",
    "WorldClosureToolPath",
    "WorldModelDraft",
    "WorldSkeletonDraft",
    "WorldStateDraft",
    "WorldStateShapeDraft",
    "WorldSemanticSourceIRDraft",
    "WorldArchitectureSourceDraft",
    "WorldRuleSemanticsSourceDraft",
    "TrainingSemanticSourceDraft",
    "WorldToolInventoryDraft",
    "WorldToolPlanInventoryDraft",
    "WorldToolSourceInventoryDraft",
    "TransitionConstraintDeltaClaimDraft",
]

"""Safe cross-component validation diagnostics and monotonic repair frontiers.

Raw exception text is not a control-plane contract: it may contain rejected
model values, filesystem paths, credentials, or Judge-private identifiers.  A
component therefore translates failures into this framework-authored record
before asking the global RepairLedger for another real Agent turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

# A safe diagnostic belongs to the framework component that owns the failed
# boundary.  This is intentionally broader than the set of Agent-capable
# components: code-only release and registry leaves also need field-addressable
# failures, even though their repair policy normally denies a semantic retry.
ValidationOwner = Literal[
    "controller",
    "research",
    "design",
    "verifier",
    "build",
    "integration",
    "judge",
    "release",
    "registry",
]

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SAFE_LOCATION_PART = re.compile(r"[^A-Za-z0-9_-]")
_SAFE_PYDANTIC_MESSAGES = {
    # Designer semantic contracts (agent_world/designer/models.py).  Each entry
    # keeps a typed validator's identity repairable: the stable code alone would
    # already be non-generic, but an Agent also needs the safe instruction and
    # expected category to correct the proposal without echoing rejected input.
    "tool_plan_read_state_duplicate": "List each read-state entity at most once.",
    "tool_plan_write_state_duplicate": "List each write-state entity at most once.",
    "tool_plan_state_footprint_empty": (
        "Declare at least one read-state or write-state entity."
    ),
    "tool_source_read_state_duplicate": "List each read-state entity at most once.",
    "tool_source_write_state_duplicate": "List each write-state entity at most once.",
    "tool_source_state_footprint_empty": (
        "Declare at least one read-state or write-state entity."
    ),
    "tool_interface_result_fields_missing": (
        "Declare at least one output field or observation field."
    ),
    "tool_semantics_inventory_mismatch": (
        "Emit tool semantics in the frozen tool inventory order, one per tool."
    ),
    "state_schema_shard_inventory_mismatch": (
        "Emit state schema shards in the frozen state inventory order."
    ),
    "tool_schema_shard_order_mismatch": (
        "Emit input, output, then observation schema shards for every tool."
    ),
    "tool_semantics_batch_tool_id_duplicate": "Reference each tool at most once per batch.",
    "group_closure_semantic_ref_arity": (
        "Provide exactly one semantic ref per member tool."
    ),
    "coupling_batch_group_order_mismatch": (
        "Keep batch members in the frozen group tool order."
    ),
    "coupling_single_batch_arity": "Emit exactly one batch for a single_batch group.",
    "coupling_multi_batch_arity": "Emit at least two batches for a multi_batch group.",
    "coupling_group_id_duplicate": "Use a unique group_id for every coupling group.",
    "coupling_tool_group_membership_duplicate": (
        "Assign every tool to exactly one coupling group."
    ),
    "coupling_execution_batch_coverage": (
        "Schedule every coupling-plan tool exactly once across execution batches."
    ),
    "world_closure_constraint_id_duplicate": "Use a unique constraint_id per constraint.",
    "world_closure_constraint_reference_unknown": (
        "Reference only constraint ids declared in the closure catalog."
    ),
    "world_closure_constraint_unreachable": (
        "Remove catalog constraints that no rule references, or reference them."
    ),
    "curriculum_task_plan_id_duplicate": "Use a unique task_type per task plan.",
    "curriculum_difficulty_dimension_duplicate": "Declare each difficulty dimension once.",
    "curriculum_coverage_dimension_duplicate": "Declare each coverage dimension once.",
    "curriculum_task_difficulty_dimension_unknown": (
        "Reference only declared curriculum difficulty dimensions."
    ),
    "state_entity_owned_resource_duplicate": "List each owned resource at most once.",
    "state_entity_visible_actor_duplicate": "List each visible actor at most once.",
    "state_entity_field_name_duplicate": "Use a unique field name per state entity.",
    "actor_authority_duplicate": "List each actor authority at most once.",
    "boundary_actor_id_duplicate": "List each boundary actor at most once.",
    "training_task_requirement_plan_mismatch": (
        "Emit task requirements in the frozen curriculum plan order, one per task."
    ),
    "environment_task_requirement_plan_mismatch": (
        "Emit task requirements in the frozen curriculum plan order, one per task."
    ),
    "assumption_origin_coverage_dimension_binding": (
        "Set coverage_dimension only for coverage_dimension origins."
    ),
    "tool_surface_delta_before_hash_binding": (
        "Omit before_hash for add; provide it for remove and modify."
    ),
    "tool_semantics_delta_before_hash_binding": (
        "Omit before_hash for add; provide it for remove and modify."
    ),
    "transition_constraint_delta_before_hash_binding": (
        "Omit before_hash for add; provide it for remove and modify."
    ),
    "task_scope_delta_before_hash_binding": (
        "Omit before_hash for add; provide it for remove and modify."
    ),
    "research_acquisition_plan_ref_type": "Bind exactly one design.research_plan ref.",
    "research_acquisition_request_ref_type": (
        "Bind exactly one control.environment_request ref."
    ),
    "research_acquisition_passage_pack_ref_type": (
        "Bind exactly one design.evidence_passage_pack ref."
    ),
    "research_acquisition_evidence_missing": (
        "Provide normalized evidence and source refs."
    ),
    "research_acquisition_evidence_id_duplicate": "Use a unique evidence_id per item.",
    "research_acquisition_source_ref_duplicate": "List each source ref at most once.",
    "research_acquisition_usage_accounting": (
        "Report real search and tool call accounting."
    ),
    "assumption_needs_human_payload_forbidden": (
        "Set both claim and fidelity to null for needs_human."
    ),
    "assumption_closure_payload_required": (
        "Provide both claim and fidelity for a closed assumption."
    ),
    "assumption_claim_disposition_mismatch": (
        "Use the claim kind/status required by the selected disposition."
    ),
    "assumption_fidelity_level_mismatch": (
        "Use the fidelity level required by the selected disposition."
    ),
    "assumption_fidelity_claim_missing": (
        "Include the new closure claim id in fidelity evidence_claim_ids."
    ),
    "assumption_known_divergence_required": (
        "Provide a non-empty known_divergence for bounded_out_of_scope."
    ),
    "rule_constant_any_forbidden": "Use one concrete JSON value_type for a constant.",
    "rule_constant_type_mismatch": "The constant value must match its declared value_type.",
    "rule_constant_non_finite": "Rule constants must use finite JSON numbers.",
    "rule_arithmetic_operand_type": "Arithmetic operands must declare number value_type.",
    "rule_arithmetic_zero_divisor": "Division and modulo cannot use a constant zero divisor.",
    "rule_unary_clause_shape": "Unary clauses cannot carry right, json_schema, or ordering.",
    "rule_schema_clause_shape": "schema_valid requires only a non-empty json_schema operand.",
    "rule_schema_empty": "schema_valid cannot use the tautological empty JSON Schema.",
    "rule_schema_invalid": "Provide a valid Draft 2020-12 JSON Schema.",
    "rule_binary_clause_shape": "Binary clauses require right and cannot carry json_schema.",
    "rule_ordering_required": "Ordered comparisons require an explicit ordering domain.",
    "rule_ordering_type_mismatch": "Ordered terms must match the declared ordering domain.",
    "rule_ordering_forbidden": "This clause operator cannot carry an ordering domain.",
    "rule_contains_left_not_container": (
        "Contains requires an array, object, string, or any left term."
    ),
    "rule_clause_id_duplicate": "Every clause_id inside one Rule must be unique.",
    "rule_pointer_not_absolute": "Use an empty pointer or an absolute RFC 6901 pointer.",
    "rule_pointer_limit": "Keep the RFC 6901 pointer within framework limits.",
    "rule_pointer_escape": "Use only ~0 and ~1 RFC 6901 escape sequences.",
    "compact_field_string_constraints": (
        "Use string value_type when setting string_format or enum_values."
    ),
    "compact_field_numeric_bounds": (
        "Use integer or number value_type when setting minimum or maximum."
    ),
    "compact_field_bounds_order": "Set minimum less than or equal to maximum.",
    "compact_field_enum_unique": "Use unique enum_values.",
    "state_field_lifecycle_contract": (
        "Use a mutable string lifecycle field with non-empty enum_values."
    ),
}
_GENERIC_NON_ACTIONABLE_CODES = frozenset(
    {
        "semantic_contract_violation",
        "schema_validation_error",
        "schema_value_error",
        "schema_value_error_root",
        "validation_error",
        "framework_diagnostic_incomplete",
    }
)
_SAFE_EXPECTED_CATEGORIES = {
    "missing": "a required field matching the closed output schema",
    "string_type": "a string value",
    "int_type": "an integer value",
    "float_type": "a numeric value",
    "bool_type": "a boolean value",
    "list_type": "an array value",
    "tuple_type": "a JSON array matching the declared item schema",
    "dict_type": "an object value",
    "literal_error": "one of the closed literal alternatives",
    "enum": "one of the closed enum alternatives",
    "extra_forbidden": "only fields declared by the closed output schema",
    "rule_constant_any_forbidden": "a concrete JSON value_type",
    "rule_constant_type_mismatch": "a constant matching its declared JSON value_type",
    "rule_constant_non_finite": "a finite JSON number",
    "rule_arithmetic_operand_type": "number-typed arithmetic operands",
    "rule_arithmetic_zero_divisor": "a non-zero constant divisor",
    "rule_unary_clause_shape": "the closed unary clause shape",
    "rule_schema_clause_shape": "the closed schema_valid clause shape",
    "rule_schema_empty": "a non-empty JSON Schema",
    "rule_schema_invalid": "a valid Draft 2020-12 JSON Schema",
    "rule_binary_clause_shape": "the closed binary clause shape",
    "rule_ordering_required": "one explicit number, date, or date-time ordering",
    "rule_ordering_type_mismatch": "terms compatible with the ordering domain",
    "rule_ordering_forbidden": "no ordering field for this operator",
    "rule_contains_left_not_container": "an array, object, string, or any left term",
    "rule_clause_id_duplicate": "unique clause_id values within the Rule",
    "rule_pointer_not_absolute": "an empty or absolute RFC 6901 pointer",
    "rule_pointer_limit": "an RFC 6901 pointer within framework limits",
    "rule_pointer_escape": "valid RFC 6901 escape sequences",
    "compact_field_string_constraints": "a string field when using string constraints",
    "compact_field_numeric_bounds": "an integer or number field when using numeric bounds",
    "compact_field_bounds_order": "a minimum less than or equal to maximum",
    "compact_field_enum_unique": "unique enum_values",
    "state_field_lifecycle_contract": (
        "a mutable string lifecycle field with non-empty enum_values"
    ),
}
# Designer semantic contracts: (violated condition, expected category).  Kept as
# one table so a typed validator cannot drift into carrying a condition without
# an expectation; both maps below are derived from it.
_DESIGNER_SEMANTIC_CONTRACTS = {
    "tool_plan_read_state_duplicate": (
        "read-state entities must be unique",
        "a read-state entity list without repeats",
    ),
    "tool_plan_write_state_duplicate": (
        "write-state entities must be unique",
        "a write-state entity list without repeats",
    ),
    "tool_plan_state_footprint_empty": (
        "a tool plan must read or write at least one state entity",
        "a non-empty read/write state footprint",
    ),
    "tool_source_read_state_duplicate": (
        "read-state entities must be unique",
        "a read-state entity list without repeats",
    ),
    "tool_source_write_state_duplicate": (
        "write-state entities must be unique",
        "a write-state entity list without repeats",
    ),
    "tool_source_state_footprint_empty": (
        "a tool source must read or write at least one state entity",
        "a non-empty read/write state footprint",
    ),
    "tool_interface_result_fields_missing": (
        "a tool interface must expose a result",
        "at least one output or observation field",
    ),
    "tool_semantics_inventory_mismatch": (
        "tool semantics must match the frozen tool inventory order and identity",
        "one semantic entry per inventory tool in inventory order",
    ),
    "state_schema_shard_inventory_mismatch": (
        "state schema shards must match the frozen state inventory order and identity",
        "one schema shard per inventory entity in inventory order",
    ),
    "tool_schema_shard_order_mismatch": (
        "tool schema shards must be ordered input/output/observation for every tool",
        "input, output, then observation shards per tool",
    ),
    "tool_semantics_batch_tool_id_duplicate": (
        "a batch must reference each tool at most once",
        "unique tool ids within one batch",
    ),
    "group_closure_semantic_ref_arity": (
        "a group closure needs one semantic ref per member tool",
        "exactly one semantic ref per member tool",
    ),
    "coupling_batch_group_order_mismatch": (
        "coupling batches must preserve the group tool order and identity",
        "batch members in frozen group tool order",
    ),
    "coupling_single_batch_arity": (
        "a single_batch group has exactly one batch",
        "exactly one batch",
    ),
    "coupling_multi_batch_arity": (
        "a multi_batch group has at least two batches",
        "two or more batches",
    ),
    "coupling_group_id_duplicate": (
        "coupling group ids must be unique",
        "a unique group_id per group",
    ),
    "coupling_tool_group_membership_duplicate": (
        "each tool belongs to exactly one coupling group",
        "disjoint coupling group membership",
    ),
    "coupling_execution_batch_coverage": (
        "execution batches schedule every coupling-plan tool exactly once",
        "exactly-once coverage of every coupling-plan tool",
    ),
    "world_closure_constraint_id_duplicate": (
        "world closure constraint ids must be unique",
        "a unique constraint_id per constraint",
    ),
    "world_closure_constraint_reference_unknown": (
        "rules may reference only catalogued constraint ids",
        "constraint references present in the closure catalog",
    ),
    "world_closure_constraint_unreachable": (
        "every catalogued constraint must be referenced by a rule",
        "a catalog with no unreferenced constraints",
    ),
    "curriculum_task_plan_id_duplicate": (
        "curriculum task plan ids must be unique",
        "a unique task_type per task plan",
    ),
    "curriculum_difficulty_dimension_duplicate": (
        "curriculum difficulty dimensions must be unique",
        "each difficulty dimension declared once",
    ),
    "curriculum_coverage_dimension_duplicate": (
        "curriculum coverage dimensions must be unique",
        "each coverage dimension declared once",
    ),
    "curriculum_task_difficulty_dimension_unknown": (
        "task plans may reference only declared difficulty dimensions",
        "difficulty references present in the curriculum plan",
    ),
    "state_entity_owned_resource_duplicate": (
        "owned resources must be unique",
        "an owned resource list without repeats",
    ),
    "state_entity_visible_actor_duplicate": (
        "visible actor ids must be unique",
        "a visible actor list without repeats",
    ),
    "state_entity_field_name_duplicate": (
        "state entity field names must be unique",
        "a unique field name per entity",
    ),
    "actor_authority_duplicate": (
        "actor authorities must be unique",
        "an authority list without repeats",
    ),
    "boundary_actor_id_duplicate": (
        "boundary actor ids must be unique",
        "a boundary actor list without repeats",
    ),
    "training_task_requirement_plan_mismatch": (
        "task requirements must match the frozen curriculum plan order and identity",
        "one requirement per plan task in plan order",
    ),
    "environment_task_requirement_plan_mismatch": (
        "task requirements must match the frozen curriculum plan order and identity",
        "one requirement per plan task in plan order",
    ),
    "assumption_origin_coverage_dimension_binding": (
        "coverage_dimension is set only for coverage_dimension origins",
        "a coverage_dimension bound to its declared origin",
    ),
    "tool_surface_delta_before_hash_binding": (
        "add forbids before_hash while remove and modify require it",
        "a before_hash consistent with the delta operation",
    ),
    "tool_semantics_delta_before_hash_binding": (
        "add forbids before_hash while remove and modify require it",
        "a before_hash consistent with the delta operation",
    ),
    "transition_constraint_delta_before_hash_binding": (
        "add forbids before_hash while remove and modify require it",
        "a before_hash consistent with the delta operation",
    ),
    "task_scope_delta_before_hash_binding": (
        "add forbids before_hash while remove and modify require it",
        "a before_hash consistent with the delta operation",
    ),
    "research_acquisition_plan_ref_type": (
        "the plan ref must be one design.research_plan",
        "one design.research_plan artifact ref",
    ),
    "research_acquisition_request_ref_type": (
        "the request ref must be one control.environment_request",
        "one control.environment_request artifact ref",
    ),
    "research_acquisition_passage_pack_ref_type": (
        "the passage pack ref must be one design.evidence_passage_pack",
        "one design.evidence_passage_pack artifact ref",
    ),
    "research_acquisition_evidence_missing": (
        "acquisition requires normalized evidence and source refs",
        "non-empty normalized evidence and source refs",
    ),
    "research_acquisition_evidence_id_duplicate": (
        "evidence ids must be unique",
        "a unique evidence_id per item",
    ),
    "research_acquisition_source_ref_duplicate": (
        "source refs must be unique",
        "a source ref list without repeats",
    ),
    "research_acquisition_usage_accounting": (
        "usage must retain real search and tool call accounting",
        "search_calls of at least one and tool_calls covering them",
    ),
}
_SAFE_EXPECTED_CATEGORIES.update(
    {code: expected for code, (_condition, expected) in _DESIGNER_SEMANTIC_CONTRACTS.items()}
)
_SAFE_VIOLATED_CONDITIONS = {
    **{code: condition for code, (condition, _expected) in _DESIGNER_SEMANTIC_CONTRACTS.items()},
    "compact_field_string_constraints": (
        "string_format and enum_values are valid only for string fields"
    ),
    "compact_field_numeric_bounds": (
        "minimum and maximum are valid only for integer or number fields"
    ),
    "compact_field_bounds_order": "minimum must not exceed maximum",
    "compact_field_enum_unique": "enum_values must be unique",
    "state_field_lifecycle_contract": (
        "lifecycle requires mutable role, string value_type, and non-empty enum_values"
    ),
}

# Per-field variants of the same uniqueness contract.  The label set mirrors the
# framework literals in the corresponding designer validators, so each field gets
# a distinct repairable identity instead of one shared generic code.
for _label in ("input", "output", "observation"):
    _code = f"tool_interface_{_label}_field_name_duplicate"
    _SAFE_PYDANTIC_MESSAGES[_code] = "Use a unique field name within this role."
    _SAFE_VIOLATED_CONDITIONS[_code] = "field names must be unique within one role"
    _SAFE_EXPECTED_CATEGORIES[_code] = "a field name list without repeats"
for _label in ("allowed_actor_ids", "required_tool_ids", "difficulty_dimensions"):
    _code = f"task_plan_{_label}_duplicate"
    _SAFE_PYDANTIC_MESSAGES[_code] = "List each value at most once in this field."
    _SAFE_VIOLATED_CONDITIONS[_code] = "task plan values must be unique within this field"
    _SAFE_EXPECTED_CATEGORIES[_code] = "a value list without repeats"
for _label in (
    "systems_of_record",
    "transition_authorities",
    "tool_namespaces",
    "core_invariants",
    "task_dimensions",
):
    _code = f"boundary_{_label}_duplicate"
    _SAFE_PYDANTIC_MESSAGES[_code] = "List each value at most once in this field."
    _SAFE_VIOLATED_CONDITIONS[_code] = "boundary source values must be unique within this field"
    _SAFE_EXPECTED_CATEGORIES[_code] = "a value list without repeats"
del _label, _code


@dataclass(frozen=True, slots=True)
class SafeValidationIssue:
    """One non-secret, field-addressable issue authored by framework code."""

    code: str
    location: tuple[str | int, ...]
    message: str
    retryable: bool = True
    violated_condition: str | None = None
    expected_category: str | None = None

    def __post_init__(self) -> None:
        if _SAFE_IDENTIFIER.fullmatch(self.code) is None:
            raise ValueError("validation issue code must be a safe identifier")
        if not self.location:
            raise ValueError("validation issue location cannot be empty")
        if not self.message or len(self.message) > 512:
            raise ValueError("validation issue message must contain at most 512 characters")
        for field_name, value in (
            ("violated_condition", self.violated_condition),
            ("expected_category", self.expected_category),
        ):
            if value is not None and (not value or len(value) > 512):
                raise ValueError(f"{field_name} must contain at most 512 characters")

    @property
    def issue_code(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"{self.code}@{location}"[:320]

    @property
    def feedback(self) -> str:
        location = ".".join(str(part) for part in self.location)
        detail = f"- {self.code} at {location}: {self.message}"
        if self.violated_condition is not None:
            detail += f" Violated condition: {self.violated_condition}."
        if self.expected_category is not None:
            detail += f" Expected: {self.expected_category}."
        return detail

    @property
    def actionable_for_agent(self) -> bool:
        """Whether this issue can safely justify spending a semantic repair turn.

        Precise legacy framework issues remain actionable while validators migrate
        to explicit condition/expectation fields.  Generic catch-all identities do
        not become actionable merely because they carry a field path.
        """

        return self.retryable and self.code not in _GENERIC_NON_ACTIONABLE_CODES

    def persistence_projection(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "location": list(self.location),
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.violated_condition is not None:
            value["violated_condition"] = self.violated_condition
        if self.expected_category is not None:
            value["expected_category"] = self.expected_category
        return value


@dataclass(frozen=True, slots=True)
class ValidationDiagnostic:
    """A complete issue set at one framework-owned validation frontier."""

    owner_component: ValidationOwner
    validation_phase: str
    frontier_ordinal: int
    issues: tuple[SafeValidationIssue, ...]

    def __post_init__(self) -> None:
        if _SAFE_IDENTIFIER.fullmatch(self.validation_phase) is None:
            raise ValueError("validation phase must be a safe identifier")
        if self.frontier_ordinal < 0:
            raise ValueError("validation frontier cannot be negative")
        if not self.issues:
            raise ValueError("validation diagnostic requires at least one issue")
        object.__setattr__(self, "issues", tuple(dict.fromkeys(self.issues)))

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.issue_code for issue in self.issues)

    @property
    def feedback(self) -> str:
        visible = self.issues[:32]
        text = "\n".join(issue.feedback for issue in visible)
        omitted = len(self.issues) - len(visible)
        if omitted:
            text += f"\n- diagnostics_overflow at root: {omitted} additional safe issues"
        return text[:8_192]

    @property
    def actionable_for_agent(self) -> bool:
        """True only when every blocker has a specific repairable identity."""

        return all(issue.actionable_for_agent for issue in self.issues)

    def persistence_projection(self) -> dict[str, object]:
        return {
            "owner_component": self.owner_component,
            "validation_phase": self.validation_phase,
            "frontier_ordinal": self.frontier_ordinal,
            "issues": [issue.persistence_projection() for issue in self.issues],
        }


class StructuredValidationError(ValueError):
    """Raise one complete safe diagnostic set from a semantic validator."""

    def __init__(self, diagnostic: ValidationDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.feedback)


def pydantic_validation_diagnostic(
    exc: ValidationError,
    *,
    owner_component: ValidationOwner,
    validation_phase: str,
    frontier_ordinal: int,
) -> ValidationDiagnostic:
    """Translate Pydantic errors without copying rejected inputs or messages."""

    issues: list[SafeValidationIssue] = []
    for item in exc.errors(include_url=False, include_context=False, include_input=False)[:64]:
        raw_error_type = str(item.get("type", "invalid"))
        error_type = re.sub(r"[^A-Za-z0-9._:-]", "-", raw_error_type)
        location = tuple(
            part
            if isinstance(part, int)
            else (_SAFE_LOCATION_PART.sub("-", str(part))[:80] or "field")
            for part in item.get("loc", ())
        ) or ("root",)
        if raw_error_type in {"value_error", "assertion_error"}:
            issues.append(
                SafeValidationIssue(
                    code="framework_diagnostic_incomplete",
                    location=location,
                    message=(
                        "A semantic validator raised an untyped error; framework code must "
                        "provide a safe condition before an Agent can repair it."
                    ),
                    retryable=False,
                    violated_condition="the validator emitted no typed semantic issue",
                    expected_category="a StructuredValidationError with a stable safe issue",
                )
            )
            continue
        expected = _SAFE_EXPECTED_CATEGORIES.get(
            raw_error_type,
            "a value satisfying the named closed-schema constraint",
        )
        issue_code = error_type if raw_error_type.startswith("rule_") else f"schema_{error_type}"
        issues.append(
            SafeValidationIssue(
                code=issue_code[:160],
                location=location,
                message=_SAFE_PYDANTIC_MESSAGES.get(
                    raw_error_type,
                    "Value does not satisfy the closed structured-output schema at this field.",
                ),
                violated_condition=_SAFE_VIOLATED_CONDITIONS.get(
                    raw_error_type,
                    f"closed schema constraint {raw_error_type}",
                ),
                expected_category=expected,
            )
        )
    if not issues:
        issues.append(
            SafeValidationIssue(
                code="schema_validation_error",
                location=("root",),
                message=(
                    "Schema validation failed without a typed field error; framework code "
                    "must disclose a safe condition before repair."
                ),
                retryable=False,
                violated_condition="the schema engine emitted no field-addressable issue",
                expected_category="at least one typed closed-schema issue",
            )
        )
    return ValidationDiagnostic(
        owner_component=owner_component,
        validation_phase=validation_phase,
        frontier_ordinal=frontier_ordinal,
        issues=tuple(issues),
    )


__all__ = [
    "SafeValidationIssue",
    "StructuredValidationError",
    "ValidationDiagnostic",
    "ValidationOwner",
    "pydantic_validation_diagnostic",
]

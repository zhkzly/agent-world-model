"""Deterministic schema closure for executable Rule references.

The Agent chooses business relations.  Framework code proves that every direct
reference and bounded collection selector can actually resolve against the
frozen execution-context schemas before Builder receives the design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import JsonValue

from agent_world.contracts import (
    Rule,
    RuleArithmetic,
    RuleConstant,
    RuleLookupByKey,
    RuleTerm,
    RuleValueRef,
    RuleValueSource,
    RuleValueType,
    StateSchema,
    ToolSurface,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.validation import SafeValidationIssue

from .models import (
    RuleArithmeticDraft,
    RuleBoundLookupByKeyDraft,
    RuleBoundReferenceDraft,
    RuleClauseDraft,
    RuleConstantDraft,
    RuleDraft,
    RuleLookupByKeyDraft,
    RuleReferenceDraft,
    ToolSemanticsBatchSourceDraft,
    ToolSemanticSourceDraft,
    WorldSkeletonDraft,
)
from .validation import StructuredSemanticError, StructuredSemanticIssue


@dataclass(frozen=True, slots=True)
class FrozenRuleReferenceBinding:
    """One framework-owned direct Rule reference exposed to a Tool Agent."""

    binding_id: str
    source: RuleValueSource
    pointer: str
    value_type: RuleValueType

    def prompt_projection(self) -> dict[str, str]:
        return {
            "binding_id": self.binding_id,
            "source": self.source,
            "pointer": self.pointer,
            "value_type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class FrozenRuleLookupBinding:
    """One indivisible collection/key/value selection owned by framework code."""

    binding_id: str
    source: Literal["pre_state", "post_state"]
    collection_pointer: str
    key_field: str
    value_pointer: str
    value_type: RuleValueType

    def prompt_projection(self) -> dict[str, str]:
        return {
            "binding_id": self.binding_id,
            "source": self.source,
            "collection_pointer": self.collection_pointer,
            "key_field": self.key_field,
            "value_pointer": self.value_pointer,
            "value_type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class RuleContextCatalog:
    """Frozen schema roots and primary-key identities visible to one tool."""

    schemas: dict[str, dict[str, JsonValue]]
    collection_keys: dict[str, tuple[str, ...]]
    collection_fields: dict[str, tuple[str, ...]]
    reference_bindings: dict[str, FrozenRuleReferenceBinding]
    lookup_bindings: dict[str, FrozenRuleLookupBinding]

    @classmethod
    def for_tool(cls, *, state: StateSchema, surface: ToolSurface) -> RuleContextCatalog:
        collection_keys: dict[str, tuple[str, ...]] = {}
        collection_fields: dict[str, tuple[str, ...]] = {}
        state_root = state.root_state_schema
        resolved_root = _dereference_schema(state_root, document=state_root)
        properties = (
            resolved_root.schema.get("properties")
            if resolved_root.failure is None and resolved_root.schema is not None
            else None
        )
        if isinstance(properties, dict):
            for root_name, root_schema in properties.items():
                if not isinstance(root_name, str) or not isinstance(root_schema, dict):
                    continue
                resolved_collection = _dereference_schema(root_schema, document=state_root)
                if (
                    resolved_collection.failure is not None
                    or resolved_collection.schema is None
                    or resolved_collection.schema.get("type") != "array"
                ):
                    continue
                items = resolved_collection.schema.get("items")
                if not isinstance(items, dict):
                    continue
                resolved_items = _dereference_schema(items, document=state_root)
                if resolved_items.failure is not None or resolved_items.schema is None:
                    continue
                item_schema = resolved_items.schema
                item_properties = item_schema.get("properties")
                if isinstance(item_properties, dict):
                    collection_fields[f"/{_escape_token(root_name)}"] = tuple(
                        sorted(str(key) for key in item_properties)
                    )
                matches = tuple(
                    entity
                    for entity in state.entities
                    if entity.json_schema == item_schema
                )
                if len(matches) == 1:
                    collection_keys[f"/{_escape_token(root_name)}"] = matches[0].primary_key_fields
        schemas = {
            "args": surface.input_schema,
            "tool_result": surface.output_schema,
            "observation": surface.observation_schema,
            "pre_state": state.root_state_schema,
            "post_state": state.root_state_schema,
        }
        catalog = cls(
            schemas=schemas,
            collection_keys=collection_keys,
            collection_fields=collection_fields,
            reference_bindings={},
            lookup_bindings={},
        )
        return cls(
            schemas=schemas,
            collection_keys=collection_keys,
            collection_fields=collection_fields,
            reference_bindings=_derive_reference_bindings(catalog),
            lookup_bindings=_derive_lookup_bindings(catalog),
        )

    def prompt_projection(self) -> dict[str, object]:
        """Bounded non-secret selector catalog for the semantic Agent prompt.

        A lookup binding is an indivisible selection, but the individual
        records share their state source, collection, and primary key with
        many sibling value fields.  Project those shared dimensions once per
        group instead of repeating them for every binding.  The immutable
        binding digests are also needlessly large in a provider prompt, so the
        projection supplies compact deterministic aliases.  This is strictly
        transport compaction: both maps below resolve back to the complete,
        framework-owned vocabulary before source materialization.
        """

        lookup_groups: dict[
            tuple[str, str, str], list[tuple[str, FrozenRuleLookupBinding]]
        ] = {}
        for alias, binding in self.prompt_lookup_bindings().items():
            lookup_groups.setdefault(
                (binding.source, binding.collection_pointer, binding.key_field),
                [],
            ).append((alias, binding))

        return {
            "collections": [
                {
                    "collection_pointer": pointer,
                    "primary_key_fields": list(self.collection_keys.get(pointer, ())),
                    "item_fields": list(self.collection_fields.get(pointer, ())),
                }
                for pointer in sorted(self.collection_fields)
            ],
            "reference_bindings": [
                {
                    "binding_id": alias,
                    "source": binding.source,
                    "pointer": binding.pointer,
                    "value_type": binding.value_type,
                }
                for alias, binding in self.prompt_reference_bindings().items()
            ],
            "lookup_binding_groups": [
                {
                    "source": source,
                    "collection_pointer": collection_pointer,
                    "key_field": key_field,
                    "value_bindings": [
                        {
                            "binding_id": alias,
                            "value_pointer": binding.value_pointer,
                            "value_type": binding.value_type,
                        }
                        for alias, binding in group
                    ],
                }
                for (source, collection_pointer, key_field), group in sorted(lookup_groups.items())
            ],
        }

    def prompt_reference_bindings(self) -> dict[str, FrozenRuleReferenceBinding]:
        """Return the exact compact prompt aliases for direct references."""

        return _prompt_binding_aliases(self.reference_bindings, prefix="ref")

    def prompt_lookup_bindings(self) -> dict[str, FrozenRuleLookupBinding]:
        """Return the exact compact prompt aliases for collection lookups."""

        return _prompt_binding_aliases(self.lookup_bindings, prefix="lookup")

    def resolve_reference_binding(self, identifier: str) -> FrozenRuleReferenceBinding | None:
        """Resolve an immutable id or one prompt-only alias without guessing."""

        return self.reference_bindings.get(identifier) or self.prompt_reference_bindings().get(
            identifier
        )

    def resolve_lookup_binding(self, identifier: str) -> FrozenRuleLookupBinding | None:
        """Resolve an immutable id or one prompt-only alias without guessing."""

        return self.lookup_bindings.get(identifier) or self.prompt_lookup_bindings().get(identifier)

    def restricted_to_state_roots(
        self,
        state_root_fields: frozenset[str],
    ) -> RuleContextCatalog:
        """Return the exact Rule vocabulary one tool may receive.

        Architecture already declares every tool's read/write entity footprint.
        A semantic batch must not receive bindings for unrelated state roots:
        doing so both expands the Agent context quadratically across a batch and
        permits a local tool to accidentally author rules against state it does
        not own.  Keep non-state bindings (args, result and observation) whole;
        filter only ``pre_state`` and ``post_state`` bindings by their first
        root JSON-pointer token.

        The returned catalog is used for both prompt projection and source
        materialization, making the disclosure boundary executable rather than
        merely an instruction to the Agent.
        """

        allowed_roots = frozenset(state_root_fields)

        def state_binding_allowed(source: str, pointer: str) -> bool:
            if source not in {"pre_state", "post_state"}:
                return True
            root = _first_pointer_token(pointer)
            return root is not None and root in allowed_roots

        def collection_allowed(pointer: str) -> bool:
            root = _first_pointer_token(pointer)
            return root is not None and root in allowed_roots

        return RuleContextCatalog(
            schemas=self.schemas,
            collection_keys={
                pointer: fields
                for pointer, fields in self.collection_keys.items()
                if collection_allowed(pointer)
            },
            collection_fields={
                pointer: fields
                for pointer, fields in self.collection_fields.items()
                if collection_allowed(pointer)
            },
            reference_bindings={
                binding_id: binding
                for binding_id, binding in self.reference_bindings.items()
                if state_binding_allowed(binding.source, binding.pointer)
            },
            lookup_bindings={
                binding_id: binding
                for binding_id, binding in self.lookup_bindings.items()
                if collection_allowed(binding.collection_pointer)
            },
        )


def materialize_tool_semantics_bindings(
    source: ToolSemanticsBatchSourceDraft,
    *,
    skeleton: WorldSkeletonDraft,
    catalogs_by_tool: Mapping[str, RuleContextCatalog] | None = None,
) -> ToolSemanticsBatchSourceDraft:
    """Expand Tool Agent binding choices into the closed executable Rule source.

    Tool semantics is the only current source boundary whose rule context is
    completely frozen before an Agent turn.  It therefore must not accept raw
    pointers, collection names, primary-key names, or declared value types as
    model-authored facts.  The Agent selects binding ids; this function derives
    the concrete Rule IR inputs and rejects every unbound escape hatch before
    legacy deterministic compilation is reached.
    """

    surfaces = {item.surface.tool_id: item.surface for item in skeleton.tool_surfaces}
    issues: list[StructuredSemanticIssue] = []
    materialized_tools: list[ToolSemanticSourceDraft] = []

    for tool_index, tool in enumerate(source.tools):
        surface = surfaces.get(tool.tool_id)
        if surface is None:
            issues.append(
                StructuredSemanticIssue(
                    code="tool_rule_binding_catalog_missing",
                    location=("tools", tool_index, "tool_id"),
                    message="The frozen ToolSurface has no Rule binding catalog.",
                    violated_condition="the ToolSemantics source names no frozen ToolSurface",
                    expected_category="one tool id from the frozen Tool batch",
                )
            )
            materialized_tools.append(tool)
            continue
        catalog = (
            catalogs_by_tool.get(tool.tool_id)
            if catalogs_by_tool is not None
            else RuleContextCatalog.for_tool(state=skeleton.state, surface=surface)
        )
        if catalog is None:
            issues.append(
                StructuredSemanticIssue(
                    code="tool_rule_binding_visibility_missing",
                    location=("tools", tool_index, "tool_id"),
                    message="The frozen ToolSurface has no disclosed Rule binding catalog.",
                    violated_condition=(
                        "the ToolSemantics source must bind exactly the framework-disclosed "
                        "Rule vocabulary for its declared state footprint"
                    ),
                    expected_category="one tool id with a frozen Rule binding catalog",
                )
            )
            materialized_tools.append(tool)
            continue
        conditions = tool.conditions.model_copy(
            update={
                "preconditions": tuple(
                    _materialize_rule_bindings(
                        rule,
                        catalog=catalog,
                        issues=issues,
                        path=("tools", tool_index, "conditions", "preconditions", rule_index),
                    )
                    for rule_index, rule in enumerate(tool.conditions.preconditions)
                ),
                "postconditions": tuple(
                    _materialize_rule_bindings(
                        rule,
                        catalog=catalog,
                        issues=issues,
                        path=("tools", tool_index, "conditions", "postconditions", rule_index),
                    )
                    for rule_index, rule in enumerate(tool.conditions.postconditions)
                ),
            }
        )
        transition = tool.state_transition.model_copy(
            update={
                "transition": tuple(
                    _materialize_rule_bindings(
                        rule,
                        catalog=catalog,
                        issues=issues,
                        path=("tools", tool_index, "state_transition", "transition", rule_index),
                    )
                    for rule_index, rule in enumerate(tool.state_transition.transition)
                )
            }
        )
        errors = tool.errors.model_copy(
            update={
                "errors": tuple(
                    error.model_copy(
                        update={
                            "when": _materialize_rule_bindings(
                                error.when,
                                catalog=catalog,
                                issues=issues,
                                path=("tools", tool_index, "errors", "errors", error_index, "when"),
                            )
                        }
                    )
                    for error_index, error in enumerate(tool.errors.errors)
                )
            }
        )
        permission = tool.access_observation.permission
        access_observation = tool.access_observation.model_copy(
            update={
                "permission": permission.model_copy(
                    update={
                        "condition": (
                            _materialize_rule_bindings(
                                permission.condition,
                                catalog=catalog,
                                issues=issues,
                                path=(
                                    "tools",
                                    tool_index,
                                    "access_observation",
                                    "permission",
                                    "condition",
                                ),
                            )
                            if permission.condition is not None
                            else None
                        )
                    }
                )
            }
        )
        materialized_tools.append(
            tool.model_copy(
                update={
                    "conditions": conditions,
                    "state_transition": transition,
                    "errors": errors,
                    "access_observation": access_observation,
                }
            )
        )

    if issues:
        raise StructuredSemanticError(tuple(issues))
    return source.model_copy(update={"tools": tuple(materialized_tools)})


def _materialize_rule_bindings(
    rule: RuleDraft,
    *,
    catalog: RuleContextCatalog,
    issues: list[StructuredSemanticIssue],
    path: tuple[str | int, ...],
) -> RuleDraft:
    clauses = tuple(
        _materialize_clause_bindings(
            clause,
            catalog=catalog,
            issues=issues,
            path=(*path, "clauses", clause_index),
        )
        for clause_index, clause in enumerate(rule.clauses)
    )
    return rule.model_copy(update={"clauses": clauses})


def _materialize_clause_bindings(
    clause: RuleClauseDraft,
    *,
    catalog: RuleContextCatalog,
    issues: list[StructuredSemanticIssue],
    path: tuple[str | int, ...],
) -> RuleClauseDraft:
    """Transform the term-bearing portion of one closed RuleClause source."""

    left = getattr(clause, "left", None)
    if left is None:
        return clause
    updates: dict[str, object] = {
        "left": _materialize_term_bindings(
            left,
            catalog=catalog,
            issues=issues,
            path=(*path, "left"),
        )
    }
    right = getattr(clause, "right", None)
    if right is not None:
        updates["right"] = _materialize_term_bindings(
            right,
            catalog=catalog,
            issues=issues,
            path=(*path, "right"),
        )
    return clause.model_copy(update=updates)


def _materialize_term_bindings(
    term: object,
    *,
    catalog: RuleContextCatalog,
    issues: list[StructuredSemanticIssue],
    path: tuple[str | int, ...],
) -> object:
    if isinstance(term, RuleConstantDraft):
        return term
    if isinstance(term, RuleBoundReferenceDraft):
        binding = catalog.resolve_reference_binding(term.binding_id)
        if binding is None:
            _binding_issue(
                issues,
                code="tool_rule_binding_unknown",
                path=(*path, "binding_id"),
                expected=_reference_binding_expectation(catalog),
            )
            return term
        return RuleReferenceDraft(
            kind="reference",
            source=binding.source,
            pointer=binding.pointer,
            value_type=binding.value_type,
        )
    if isinstance(term, RuleBoundLookupByKeyDraft):
        lookup_binding = catalog.resolve_lookup_binding(term.binding_id)
        if lookup_binding is None:
            _binding_issue(
                issues,
                code="tool_rule_binding_unknown",
                path=(*path, "binding_id"),
                expected=_lookup_binding_expectation(catalog),
            )
            return term
        key = _materialize_term_bindings(
            term.key,
            catalog=catalog,
            issues=issues,
            path=(*path, "key"),
        )
        if not isinstance(key, RuleConstantDraft | RuleReferenceDraft):
            _binding_issue(
                issues,
                code="tool_rule_lookup_key_binding_required",
                path=(*path, "key"),
                expected="a constant or one frozen reference binding",
            )
            return term
        return RuleLookupByKeyDraft(
            kind="lookup_by_key",
            source=lookup_binding.source,
            collection_pointer=lookup_binding.collection_pointer,
            key_field=lookup_binding.key_field,
            key=key,
            value_pointer=lookup_binding.value_pointer,
            value_type=lookup_binding.value_type,
        )
    if isinstance(term, RuleReferenceDraft | RuleLookupByKeyDraft):
        _binding_issue(
            issues,
            code="tool_rule_binding_required",
            path=path,
            expected="a bound_reference or bound_lookup_by_key from the frozen catalog",
        )
        return term
    if isinstance(term, RuleArithmeticDraft):
        return term.model_copy(
            update={
                "left": _materialize_term_bindings(
                    term.left,
                    catalog=catalog,
                    issues=issues,
                    path=(*path, "left"),
                ),
                "right": _materialize_term_bindings(
                    term.right,
                    catalog=catalog,
                    issues=issues,
                    path=(*path, "right"),
                ),
            }
        )
    raise TypeError(f"unsupported Tool Rule term: {type(term).__name__}")


def _binding_issue(
    issues: list[StructuredSemanticIssue],
    *,
    code: str,
    path: tuple[str | int, ...],
    expected: str,
) -> None:
    issues.append(
        StructuredSemanticIssue(
            code=code,
            location=path,
            message="ToolSemantics must select only one framework-derived Rule binding.",
            violated_condition=(
                "the ToolSemantics source used a Rule reference that is not bound "
                "to the frozen execution schema"
            ),
            expected_category=expected,
        )
    )


def _derive_reference_bindings(
    catalog: RuleContextCatalog,
) -> dict[str, FrozenRuleReferenceBinding]:
    bindings: dict[str, FrozenRuleReferenceBinding] = {}
    for source, schema in sorted(catalog.schemas.items()):
        if source not in {"args", "tool_result", "observation", "pre_state", "post_state"}:
            continue
        for pointer, value_type in _iter_direct_schema_bindings(schema, document=schema):
            binding_id = _binding_id(
                "reference",
                {
                    "source": source,
                    "pointer": pointer,
                    "value_type": value_type,
                },
            )
            bindings[binding_id] = FrozenRuleReferenceBinding(
                binding_id=binding_id,
                source=cast(RuleValueSource, source),
                pointer=pointer,
                value_type=value_type,
            )
    return bindings


def _derive_lookup_bindings(
    catalog: RuleContextCatalog,
) -> dict[str, FrozenRuleLookupBinding]:
    bindings: dict[str, FrozenRuleLookupBinding] = {}
    for source in ("pre_state", "post_state"):
        schema = catalog.schemas[source]
        for collection_pointer, fields in sorted(catalog.collection_fields.items()):
            keys = catalog.collection_keys.get(collection_pointer, ())
            collection = _resolve_schema_pointer(
                schema,
                collection_pointer,
                document=schema,
            )
            if (
                collection.failure is not None
                or collection.schema is None
                or collection.schema.get("type") != "array"
            ):
                continue
            raw_items = collection.schema.get("items")
            if not isinstance(raw_items, dict):
                continue
            item = _dereference_schema(raw_items, document=schema)
            if item.failure is not None or item.schema is None:
                continue
            for key_field in keys:
                for field in fields:
                    value = _resolve_schema_pointer(
                        item.schema,
                        f"/{_escape_token(field)}",
                        document=schema,
                    )
                    if value.failure is not None or value.schema is None:
                        continue
                    value_type = _schema_binding_value_type(value.schema)
                    value_pointer = f"/{_escape_token(field)}"
                    binding_id = _binding_id(
                        "lookup",
                        {
                            "source": source,
                            "collection_pointer": collection_pointer,
                            "key_field": key_field,
                            "value_pointer": value_pointer,
                            "value_type": value_type,
                        },
                    )
                    bindings[binding_id] = FrozenRuleLookupBinding(
                        binding_id=binding_id,
                        source=source,
                        collection_pointer=collection_pointer,
                        key_field=key_field,
                        value_pointer=value_pointer,
                        value_type=value_type,
                    )
    return bindings


def _iter_direct_schema_bindings(
    schema: dict[str, JsonValue],
    *,
    document: dict[str, JsonValue],
) -> tuple[tuple[str, RuleValueType], ...]:
    """Enumerate direct pointers without fabricating selectors through arrays."""

    collected: list[tuple[str, RuleValueType]] = []

    def visit(value: dict[str, JsonValue], pointer: str) -> None:
        resolved = _dereference_schema(value, document=document)
        if resolved.failure is not None or resolved.schema is None:
            return
        current = resolved.schema
        collected.append((pointer, _schema_binding_value_type(current)))
        if current.get("type") != "object":
            return
        properties = current.get("properties")
        if not isinstance(properties, dict):
            return
        for field, child in sorted(properties.items()):
            if isinstance(field, str) and isinstance(child, dict):
                visit(child, _join_pointer(pointer, field))

    visit(schema, "")
    return tuple(collected)


def _schema_binding_value_type(schema: dict[str, JsonValue]) -> RuleValueType:
    values = _schema_value_types(schema)
    return next(iter(values)) if len(values) == 1 else "any"


def _binding_id(kind: str, payload: dict[str, object]) -> str:
    digest = sha256_digest(canonical_json_bytes(payload)).removeprefix("sha256:")
    return f"binding:{kind}:{digest[:24]}"


def _prompt_binding_aliases[TBinding](
    bindings: Mapping[str, TBinding],
    *,
    prefix: str,
) -> dict[str, TBinding]:
    """Assign compact deterministic aliases to one frozen binding vocabulary.

    The Agent sees aliases only in a frozen prompt projection and can select
    only one of them. The source materializer resolves an alias before any
    executable Rule compiler sees it, so aliases cannot author source,
    pointers, keys, types, or an unlisted binding.
    """

    width = max(1, len(str(len(bindings))))
    return {
        f"{prefix}-{ordinal:0{width}d}": binding
        for ordinal, (_original_id, binding) in enumerate(sorted(bindings.items()), start=1)
    }


def _first_pointer_token(pointer: str) -> str | None:
    """Return the unescaped first token of a non-root JSON pointer."""

    if not pointer.startswith("/"):
        return None
    token = pointer.removeprefix("/").split("/", 1)[0]
    return token.replace("~1", "/").replace("~0", "~")


def _join_pointer(parent: str, token: str) -> str:
    return f"{parent}/{_escape_token(token)}" if parent else f"/{_escape_token(token)}"


def _reference_binding_expectation(catalog: RuleContextCatalog) -> str:
    return _bounded_expectation(
        "one frozen reference binding id or prompt alias",
        tuple(catalog.prompt_reference_bindings()),
    )


def _lookup_binding_expectation(catalog: RuleContextCatalog) -> str:
    return _bounded_expectation(
        "one frozen lookup binding id or prompt alias",
        tuple(catalog.prompt_lookup_bindings()),
    )


@dataclass(frozen=True, slots=True)
class _Resolution:
    schema: dict[str, JsonValue] | None
    failure: Literal["missing", "selector_required", "invalid_schema"] | None = None


def validate_rule_context(
    rule: Rule,
    *,
    catalog: RuleContextCatalog,
) -> tuple[SafeValidationIssue, ...]:
    """Return every safe reference/selector closure issue in one Rule."""

    issues: list[SafeValidationIssue] = []

    def validate_term(term: RuleTerm, path: tuple[str | int, ...]) -> None:
        if isinstance(term, RuleConstant):
            return
        if isinstance(term, RuleValueRef):
            schema = catalog.schemas.get(term.source)
            if schema is None:
                return
            resolution = _resolve_schema_pointer(schema, term.pointer, document=schema)
            if resolution.failure is not None:
                issues.append(
                    _reference_failure(
                        path=path,
                        pointer_path=(*path, "pointer"),
                        failure=resolution.failure,
                    )
                )
                return
            assert resolution.schema is not None
            _validate_declared_type(
                term.value_type,
                resolution.schema,
                path=(*path, "value_type"),
                issues=issues,
            )
            return
        if isinstance(term, RuleLookupByKey):
            validate_term(term.key, (*path, "key"))
            root = catalog.schemas.get(term.source)
            if root is None:
                return
            collection = _resolve_schema_pointer(
                root,
                term.collection_pointer,
                document=root,
            )
            if collection.failure is not None or collection.schema is None:
                issues.append(
                    _reference_failure(
                        path=path,
                        pointer_path=(*path, "collection_pointer"),
                        failure=collection.failure or "missing",
                    )
                )
                return
            if collection.schema.get("type") != "array" or not isinstance(
                collection.schema.get("items"), dict
            ):
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_collection_not_array",
                        location=(*path, "collection_pointer"),
                        message="lookup_by_key must target an array with an object item schema.",
                        violated_condition="the selector collection target is not an array",
                        expected_category=_allowed_collection_expectation(catalog),
                    )
                )
                return
            raw_item_schema = collection.schema["items"]
            assert isinstance(raw_item_schema, dict)
            item_resolution = _dereference_schema(raw_item_schema, document=root)
            if item_resolution.failure is not None or item_resolution.schema is None:
                issues.append(
                    SafeValidationIssue(
                        code="framework_rule_context_schema_invalid",
                        location=(*path, "collection_pointer"),
                        message=(
                            "The frozen Rule context catalog contains an unresolved "
                            "collection item schema."
                        ),
                        retryable=False,
                        violated_condition=(
                            "the framework context collection item schema cannot be resolved"
                        ),
                        expected_category="one closed local JSON Schema item definition",
                    )
                )
                return
            item_schema = item_resolution.schema
            item_properties = item_schema.get("properties")
            raw_key_schema = (
                item_properties.get(term.key_field)
                if isinstance(item_properties, dict)
                else None
            )
            key_resolution = (
                _dereference_schema(raw_key_schema, document=root)
                if isinstance(raw_key_schema, dict)
                else _Resolution(None, "missing")
            )
            key_schema = key_resolution.schema if key_resolution.failure is None else None
            if not isinstance(key_schema, dict):
                declared_fields = (
                    tuple(sorted(str(key) for key in item_properties))
                    if isinstance(item_properties, dict)
                    else ()
                )
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_key_field_missing",
                        location=(*path, "key_field"),
                        message="lookup_by_key key_field must exist in the collection item schema.",
                        violated_condition="the selector key_field is absent from item properties",
                        expected_category=_bounded_expectation(
                            "one of the item fields",
                            declared_fields,
                        ),
                    )
                )
            allowed_keys = catalog.collection_keys.get(term.collection_pointer)
            if allowed_keys is not None and term.key_field not in allowed_keys:
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_key_not_primary",
                        location=(*path, "key_field"),
                        message="lookup_by_key must use a frozen primary-key field.",
                        violated_condition="the selector key_field is not a collection primary key",
                        expected_category=_bounded_expectation(
                            "one of the frozen primary-key fields",
                            allowed_keys,
                        ),
                    )
                )
            value = _resolve_schema_pointer(
                item_schema,
                term.value_pointer,
                document=root,
            )
            if value.failure is not None or value.schema is None:
                if value.failure == "missing" and isinstance(item_properties, dict):
                    issues.append(
                        SafeValidationIssue(
                            code="rule_pointer_unreachable",
                            location=(*path, "value_pointer"),
                            message="The pointer does not resolve in the collection item schema.",
                            violated_condition="the selected-record field path does not exist",
                            expected_category=_bounded_expectation(
                                "one of the item pointers",
                                tuple(
                                    f"/{_escape_token(str(key))}"
                                    for key in sorted(item_properties)
                                ),
                            ),
                        )
                    )
                else:
                    issues.append(
                        _reference_failure(
                            path=path,
                            pointer_path=(*path, "value_pointer"),
                            failure=value.failure or "missing",
                        )
                    )
            else:
                _validate_declared_type(
                    term.value_type,
                    value.schema,
                    path=(*path, "value_type"),
                    issues=issues,
                )
            if isinstance(key_schema, dict):
                key_type = _term_declared_type(term.key)
                if key_type is not None:
                    _validate_declared_type(
                        key_type,
                        key_schema,
                        path=(*path, "key", "value_type"),
                        issues=issues,
                    )
            return
        if isinstance(term, RuleArithmetic):
            validate_term(term.left, (*path, "left"))
            validate_term(term.right, (*path, "right"))
            return
        raise TypeError(f"unsupported Rule term: {type(term).__name__}")

    for clause_index, clause in enumerate(rule.clauses):
        validate_term(clause.left, ("clauses", clause_index, "left"))
        if clause.right is not None:
            validate_term(clause.right, ("clauses", clause_index, "right"))
    return tuple(dict.fromkeys(issues))


def _resolve_schema_pointer(
    schema: dict[str, JsonValue],
    pointer: str,
    *,
    document: dict[str, JsonValue],
) -> _Resolution:
    current_resolution = _dereference_schema(schema, document=document)
    if current_resolution.failure is not None or current_resolution.schema is None:
        return current_resolution
    current = current_resolution.schema
    if pointer == "":
        return _Resolution(current)
    for raw_token in pointer.removeprefix("/").split("/"):
        current_resolution = _dereference_schema(current, document=document)
        if current_resolution.failure is not None or current_resolution.schema is None:
            return current_resolution
        current = current_resolution.schema
        token = raw_token.replace("~1", "/").replace("~0", "~")
        schema_type = current.get("type")
        if schema_type == "object":
            properties = current.get("properties")
            child = properties.get(token) if isinstance(properties, dict) else None
            if not isinstance(child, dict):
                return _Resolution(None, "missing")
            current = child
            continue
        if schema_type == "array":
            if not token.isdecimal():
                return _Resolution(None, "selector_required")
            items = current.get("items")
            if not isinstance(items, dict):
                return _Resolution(None, "invalid_schema")
            current = items
            continue
        return _Resolution(None, "missing")
    return _dereference_schema(current, document=document)


def _dereference_schema(
    schema: dict[str, JsonValue],
    *,
    document: dict[str, JsonValue],
) -> _Resolution:
    """Resolve a finite chain of local JSON Schema ``$ref`` values.

    WorldState composes entity schemas under ``$defs`` and root collections
    point at those definitions.  Rule references target the *resolved* runtime
    shape, not the transport representation of that schema.  External or
    cyclic references are deliberately rejected as invalid framework context;
    the Designer never follows a network reference while compiling an
    executable environment.
    """

    current = schema
    visited: set[str] = set()
    while "$ref" in current:
        raw_ref = current.get("$ref")
        if not isinstance(raw_ref, str) or not raw_ref.startswith("#"):
            return _Resolution(None, "invalid_schema")
        if raw_ref in visited:
            return _Resolution(None, "invalid_schema")
        visited.add(raw_ref)
        target = _resolve_local_ref(document, raw_ref)
        if target is None:
            return _Resolution(None, "invalid_schema")
        current = target
    return _Resolution(current)


def _resolve_local_ref(
    document: dict[str, JsonValue],
    reference: str,
) -> dict[str, JsonValue] | None:
    """Resolve one local RFC 6901 fragment without accepting external refs."""

    if reference == "#":
        return document
    if not reference.startswith("#/"):
        return None
    current: JsonValue = document
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict):
            return None
        current = current.get(token)
        if current is None:
            return None
    return current if isinstance(current, dict) else None


def _reference_failure(
    *,
    path: tuple[str | int, ...],
    pointer_path: tuple[str | int, ...],
    failure: Literal["missing", "selector_required", "invalid_schema"],
) -> SafeValidationIssue:
    if failure == "selector_required":
        return SafeValidationIssue(
            code="rule_pointer_requires_selector",
            location=pointer_path,
            message="A direct JSON pointer cannot select a dynamic collection record.",
            violated_condition="the pointer traverses an array without a fixed index or selector",
            expected_category="lookup_by_key for dynamic state records or a fixed numeric index",
        )
    if failure == "invalid_schema":
        return SafeValidationIssue(
            code="framework_rule_context_schema_invalid",
            location=path,
            message="The frozen Rule context catalog contains an unsupported array schema.",
            retryable=False,
            violated_condition="the framework context schema has no single item schema",
            expected_category="one closed array item schema",
        )
    return SafeValidationIssue(
        code="rule_pointer_unreachable",
        location=pointer_path,
        message="The pointer does not resolve in the frozen source schema.",
        violated_condition="the referenced schema path does not exist",
        expected_category="a pointer reachable from the selected source schema",
    )


def _validate_declared_type(
    declared: RuleValueType,
    schema: dict[str, JsonValue],
    *,
    path: tuple[str | int, ...],
    issues: list[SafeValidationIssue],
) -> None:
    expected = _schema_value_types(schema)
    if not expected or declared == "any" or declared in expected:
        return
    issues.append(
        SafeValidationIssue(
            code="rule_reference_type_mismatch",
            location=path,
            message="Rule reference value_type must match the frozen source schema.",
            violated_condition="the Agent-declared value_type differs from schema-derived type",
            expected_category="one of " + ", ".join(sorted(expected)),
        )
    )


def _schema_value_types(schema: dict[str, JsonValue]) -> frozenset[RuleValueType]:
    raw = schema.get("type")
    values = (raw,) if isinstance(raw, str) else tuple(raw) if isinstance(raw, list) else ()
    mapped: set[RuleValueType] = set()
    for value in values:
        if value == "integer":
            mapped.add("number")
        elif isinstance(value, str) and value in {
            "null",
            "boolean",
            "number",
            "string",
            "array",
            "object",
        }:
            mapped.add(cast(RuleValueType, value))
    return frozenset(mapped)


def _term_declared_type(term: RuleConstant | RuleValueRef) -> RuleValueType | None:
    return term.value_type


def _escape_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _allowed_collection_expectation(catalog: RuleContextCatalog) -> str:
    return _bounded_expectation(
        "one of the frozen collection pointers",
        tuple(sorted(catalog.collection_keys)),
    )


def _bounded_expectation(label: str, values: tuple[str, ...]) -> str:
    if not values:
        return label
    rendered = f"{label}: {', '.join(values)}"
    return rendered if len(rendered) <= 512 else f"{rendered[:509]}..."


__all__ = [
    "FrozenRuleLookupBinding",
    "FrozenRuleReferenceBinding",
    "RuleContextCatalog",
    "materialize_tool_semantics_bindings",
    "validate_rule_context",
]

"""Typed, bounded producer transactions for the Direct DesignGraph."""

from __future__ import annotations

import json
import math
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agent_world.artifacts import ArtifactStore, safe_url
from agent_world.config import ConfigurationError, FoundrySettings, credential_from_environment
from agent_world.contracts import (
    ArtifactRef,
    AssuranceRecipe,
    CitationCatalog,
    CitationCatalogItem,
    CorrectionPacket,
    CurriculumFamily,
    CurriculumPlan,
    DesignContract,
    DifficultyDimension,
    DifficultyLevel,
    EffectDraft,
    EntityDeclaration,
    EnvironmentRequest,
    EvaluatorGoalBinding,
    EvidenceClaim,
    EvidenceGraph,
    ExecutableTaskContract,
    ExpectedOutputCategory,
    FieldDeclaration,
    OperationEvidence,
    PredicateDraft,
    ResearchPlan,
    RewardSpec,
    RuleDraft,
    SemanticBinding,
    SemanticCatalog,
    SharedToolContract,
    TaskRequirement,
    TerminalStatus,
    TerminationSpec,
    ToolCouplingPlan,
    ToolDraft,
    ToolSurface,
    VerificationRequirements,
    WorldArchitecture,
    WorldBoundary,
    WorldRuleSet,
    compile_difficulty_schema,
    digest_value,
    json_value,
)
from agent_world.graph import GraphRunner, NodeExecutionError, ResumeContext
from agent_world.runtime import _guard_arguments, _predicates, _task_bindings, _value
from agent_world.invocation import (
    CodexAgentBackend,
    DirectChatBackend,
    InvocationError,
    InvocationResult,
    _DirectFormatFailure,
)

_URL = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PENDING = ArtifactRef("pending", "pending", "sha256:" + "0" * 64, "artifacts/pending.json")


class DesignError(NodeExecutionError):
    def __init__(
        self,
        code: str,
        status: TerminalStatus = "rejected",
        retryable: bool = False,
        *,
        correctable: bool = True,
        path: str = "$",
        violated_condition: str = "output must satisfy the closed node contract",
        expected_category: ExpectedOutputCategory = "object",
    ) -> None:
        super().__init__(
            code,
            status,
            retryable,
            correction=(
                CorrectionPacket(code, path, violated_condition, expected_category)
                if correctable and status == "rejected" and not retryable
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DesignResult:
    design: DesignContract
    work_refs: tuple[ArtifactRef, ...]
    artifact_refs: tuple[ArtifactRef, ...]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _direct_feedback(correction: CorrectionPacket) -> str:
    context = (
        "Continue the same task with the original frozen input and complete output contract. "
        "The immediately preceding complete proposal was rejected for one safe framework-observed "
        f"issue: code {correction.code}; path {correction.path}; "
        f"condition {correction.violated_condition}; expected category "
        f"{correction.expected_category}."
    )
    if correction.code == "direct_response_not_json":
        repair = (
            "\n\nREJECTED: the answer was not one parseable JSON object.\n\n"
            "FIX: replace the entire immediately preceding answer with one parseable JSON "
            "object. Delete all prose, labels, Markdown fences, and second JSON values. "
            "Its first and last non-whitespace characters must be { and }."
        )
    else:
        repair = (
            "\n\nREJECTED: the framework validates one field at a time and stops at the "
            "FIRST violation. The flagged path is the first problem found, not necessarily "
            "the only one.\n\n"
            "FIX: correct the response at the flagged path, then recheck EVERY field in "
            "the complete immediately preceding proposal and fix all same-kind violations "
            "before resubmitting."
        )
    return (
        context
        + repair
        + "\n\nRESUBMIT: return one complete replacement as exactly one JSON object, not a "
        "patch, explanation, or Markdown. Before answering, self-check the whole replacement "
        "object against the complete output contract."
    )


def _text(value: object, code: str, limit: int = 500, *, path: str = "$") -> str:
    if not isinstance(value, str):
        raise DesignError(
            code,
            path=path,
            violated_condition="value must be a string",
            expected_category="string",
        )
    stripped = value.strip()
    if not stripped:
        raise DesignError(
            code,
            path=path,
            violated_condition="value must be nonempty after stripping",
            expected_category="string",
        )
    if len(stripped) > limit:
        raise DesignError(
            code,
            path=path,
            violated_condition=f"value must use at most {limit} code points; got {len(stripped)}",
            expected_category="string",
        )
    return stripped


def _short_keys(keys: list[Any], cap: int = 3) -> str:
    """Render up to *cap* offending keys with an overflow suffix (bounded)."""

    shown = [str(key) for key in keys[:cap]]
    text = ", ".join(shown)
    if len(keys) > cap:
        text += f" …(+{len(keys) - cap})"
    return text


def _object_violation(value: object, keys: set[str]) -> str:
    """Render the closed-object violation with the actual offenders, bounded
    by the CorrectionPacket 280-character budget (contracts.py)."""

    expected = (
        "object must contain exactly these fields and no others: " + ", ".join(sorted(keys))
    )
    if not isinstance(value, dict):
        return expected + "; the rejected value was not an object"
    extra = sorted((key for key in value if key not in keys), key=str)
    missing = sorted((key for key in keys if key not in value), key=str)
    detail: list[str] = []
    if extra:
        detail.append("extra keys: " + _short_keys(extra))
    if missing:
        detail.append("missing keys: " + _short_keys(missing))
    if not detail:
        return expected
    text = expected + "; rejected object " + "; ".join(detail)
    if len(text) <= 280:
        return text
    return text[:277] + "..."


def _object(value: object, keys: set[str], code: str, *, path: str = "$") -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DesignError(
            code,
            path=path,
            violated_condition=_object_violation(value, keys),
            expected_category="object",
        )
    return value


def _array(value: object, minimum: int, maximum: int, code: str, *, path: str = "$") -> list[Any]:
    actual = len(value) if isinstance(value, list) else None
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        detail = (
            f"; the rejected value had {actual} items"
            if isinstance(value, list)
            else "; the rejected value was not an array"
        )
        raise DesignError(
            code,
            path=path,
            violated_condition=(
                f"array must contain between {minimum} and {maximum} items inclusive{detail}"
            ),
            expected_category="array",
        )
    return value


def _json_scalar(value: object) -> bool:
    return value is None or (
        type(value) in {bool, int, float, str}
        and not (type(value) is float and not math.isfinite(value))
    )


def _model_value(value: Any) -> Any:
    """Project only compiled semantics, never framework artifact identities."""

    raw = json_value(value)
    if isinstance(raw, dict):
        return {
            key: _model_value(item)
            for key, item in raw.items()
            if key not in {"artifact", "work_refs"}
        }
    if isinstance(raw, list):
        return [_model_value(item) for item in raw]
    return raw


def _design_artifact_value(value: DesignContract) -> dict[str, Any]:
    """Persist the complete safe Design projection without evaluator-private labels."""

    def project(raw: Any) -> Any:
        if isinstance(raw, dict):
            return {
                {
                    "evaluator_goal_bindings": "goal_bindings",
                    "evaluator_goal_path": "goal_path",
                }.get(key, key): project(item)
                for key, item in raw.items()
            }
        if isinstance(raw, list):
            return [project(item) for item in raw]
        return raw

    return cast(dict[str, Any], project(json_value(replace(value, artifact=_PENDING))))


def _json_value(value: object) -> bool:
    return _json_scalar(value) or (
        isinstance(value, list) and len(value) <= 32 and all(_json_scalar(item) for item in value)
    )


def _source_urls(body: str) -> tuple[str, ...]:
    urls: list[str] = []
    for found in _URL.finditer(body):
        value = found.group(0).rstrip(".,;:)")
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or host == "localhost"
            or host.endswith(".local")
            or host.endswith("jina.ai")
        ):
            continue
        if value not in urls:
            urls.append(value)
        if len(urls) == 6:
            break
    return tuple(urls)


def _field(value: object, code: str, *, path: str) -> FieldDeclaration:
    raw = value if isinstance(value, dict) else {}
    if (
        not {"name", "category", "required"}
        <= set(raw)
        <= {"name", "category", "required", "values", "entity_ref"}
    ):
        raise DesignError(
            code,
            path=path,
            violated_condition="field must use the sparse declared keys",
            expected_category="object",
        )
    name = _text(raw["name"], code, 64, path=f"{path}.name")
    if (
        not _NAME.fullmatch(name)
        or raw["category"]
        not in {"text", "integer", "number", "boolean", "timestamp", "identifier", "enum", "list"}
        or type(raw["required"]) is not bool
    ):
        raise DesignError(
            code,
            path=path,
            violated_condition="field name, category, and required flag must be valid",
            expected_category="object",
        )
    finite = raw["category"] in {"enum", "list"}
    if ("values" in raw) != finite:
        raise DesignError(
            code,
            path=f"{path}.values",
            violated_condition="enum/list fields require nonempty values; scalars must omit them",
            expected_category="array",
        )
    values = _array(raw.get("values", []), 1, 16, code, path=f"{path}.values") if finite else []
    if any(not isinstance(item, str) or not item.strip() for item in values) or len(
        set(values)
    ) != len(values):
        raise DesignError(
            code,
            path=f"{path}.values",
            violated_condition="finite field domains must be unique text",
            expected_category="array",
        )
    entity_ref = raw.get("entity_ref")
    if "entity_ref" in raw and (not isinstance(entity_ref, str) or not _NAME.fullmatch(entity_ref)):
        raise DesignError(
            code,
            path=f"{path}.entity_ref",
            violated_condition="entity reference must name a declared entity",
            expected_category="string",
        )
    return FieldDeclaration(name, raw["category"], raw["required"], tuple(values), entity_ref)


def _rule_id(tool_index: int, section: str, ordinal: int) -> str:
    return f"tool:{tool_index}:{section}:{ordinal}"


def _local_rules_digest(
    tool_index: int,
    bindings: tuple[SemanticBinding, ...],
    preconditions: tuple[RuleDraft, ...],
    transitions: tuple[RuleDraft, ...],
    postconditions: tuple[RuleDraft, ...],
    errors: tuple[RuleDraft, ...],
    shared_contract_digest: str | None = None,
) -> str:
    return (
        "sha256:"
        + sha256(
            _canonical(
                {
                    "tool_index": tool_index,
                    "bindings": json_value(bindings),
                    "preconditions": json_value(preconditions),
                    "transitions": json_value(transitions),
                    "postconditions": json_value(postconditions),
                    "errors": json_value(errors),
                    "shared_contract_digest": shared_contract_digest,
                }
            )
        ).hexdigest()
    )


_PREDICATE_OPERATORS = frozenset({
    "eq", "ne", "lt", "le", "gt", "ge",
    "contains", "not_contains", "exists", "not_exists",
})
_EFFECT_OPERATIONS = frozenset({
    "set", "increment", "decrement", "add", "remove", "preserve", "reject",
})
_EXISTENCE_OPERATORS = frozenset({"exists", "not_exists"})
_NO_VALUE_OPERATIONS = frozenset({"preserve", "reject"})
_RULE_KEYS = {"when", "effects", "error_kind", "rationale", "citation_indexes"}
_TASK_RULE_KEYS = {"when", "effects", "rationale", "citation_indexes"}

_PREDICATE_EFFECT_SHAPE = (
    "Predicate object (exactly these keys — OMIT value for exists/not_exists):\n"
    "  field    : string — the NAME of a declared field from the field list in the input (NOT an index)\n"  # noqa: E501
    "  operator : one of eq|ne|lt|le|gt|ge|contains|not_contains|exists|not_exists\n"
    "  value    : JSON scalar or scalar-list[0..32] — the comparison literal\n\n"
    "Effect object (exactly these keys — OMIT value for preserve/reject):\n"
    "  field     : string — the NAME of a declared field from the field list in the input (NOT an index)\n"  # noqa: E501
    "  operation : one of set|increment|decrement|add|remove|preserve|reject\n"
    "  value     : JSON scalar or scalar-list[0..32] — the new value\n"
)
_RULE_DRAFT_SHAPE = (
    "RuleDraft (exactly these keys, no others):\n"
    "  when             : array[0..6] of predicate objects (may be empty)\n"
    "  effects          : array[1..6] of effect objects (at least one)\n"
    "  error_kind       : null in non-error sections; snake_case [a-z][a-z0-9_]{0,63} in errors-only sections\n"  # noqa: E501
    "  rationale        : nonempty stripped text <=300 code points\n"
    "  citation_indexes : array[0..8] of unique frozen CitationCatalog one-based indexes; [] when no catalog is supplied\n\n"  # noqa: E501
    + _PREDICATE_EFFECT_SHAPE
    + "\nExample RuleDraft (non-error): "
    '{"when":[{"field":"status","operator":"eq","value":"open"}],'
    '"effects":[{"field":"status","operation":"set","value":"assigned"}],'
    '"error_kind":null,"rationale":"assign open ticket","citation_indexes":[1]}'
)
_TASK_RULE_DRAFT_SHAPE = (
    "TaskRequirementRuleDraft (exactly these keys, no others):\n"
    "  when             : array[0..6] of predicate objects (may be empty)\n"
    "  effects          : array[1..6] of effect objects (at least one)\n"
    "  rationale        : nonempty stripped text <=300 code points\n"
    "  citation_indexes : array[0..8] of unique frozen CitationCatalog one-based indexes\n\n"
    + _PREDICATE_EFFECT_SHAPE
    + "\nExample TaskRequirementRuleDraft: "
    '{"when":[{"field":"status","operator":"eq","value":"open"}],'
    '"effects":[{"field":"status","operation":"set","value":"resolved"}],'
    '"rationale":"mark task resolved","citation_indexes":[1]}'
)


def _name_to_index(
    bindings: tuple[SemanticBinding, ...],
) -> dict[str, int]:
    """Build a field-name to semantic-index map (last binding wins on collision)."""

    return {binding.name: binding.index for binding in bindings}


_GOAL_SOURCE_PREFERENCE = ("post_state", "tool_result", "argument", "pre_state", "reset_state")


def _goal_name_lookup(
    architecture: WorldArchitecture,
    family_tool_indexes: tuple[int, ...] | None = None,
) -> dict[str, int]:
    """Qualified + unambiguous-bare name -> semantic index map for goal fields.

    Qualified names (tool.field) resolve deterministically by source
    preference (post_state > tool_result > argument > pre_state >
    reset_state); reset_state is a cast-bypassed catalog source (see
    _catalog) and ranks last. Bare names are accepted only when globally
    unambiguous, mirroring _section_lookup's convention and removing the
    silent last-wins misresolution. When family_tool_indexes is given the
    map is restricted to those tools (used to render the valid-name hint).
    """

    tool_name_by_index = {tool.tool_index: tool.name for tool in architecture.tools}
    tool_indexes = set(family_tool_indexes) if family_tool_indexes is not None else None
    qualified: dict[str, list[SemanticBinding]] = {}
    bare_seen: dict[str, int] = {}
    for binding in architecture.catalog.bindings:
        tool_index = int(binding.path[1])
        if tool_indexes is not None and tool_index not in tool_indexes:
            continue
        tool_name = tool_name_by_index.get(tool_index, "tool_" + str(tool_index))
        qualified.setdefault(tool_name + "." + binding.name, []).append(binding)
        if binding.name in bare_seen:
            bare_seen[binding.name] = -1
        else:
            bare_seen[binding.name] = binding.index
    lookup: dict[str, int] = {}
    for name, candidates in qualified.items():
        for source in _GOAL_SOURCE_PREFERENCE:
            for binding in candidates:
                if binding.source == source:
                    lookup[name] = binding.index
                    break
            else:
                continue
            break
    for name, index in bare_seen.items():
        if index != -1:
            lookup[name] = index
    return lookup


def _goal_field_correction(
    rejected: object, valid_lookup: dict[str, int], ambiguity_note: str | None = None
) -> str:
    """Render the unknown/ambiguous goal-field correction inside the
    CorrectionPacket budget: always name the rejected field, add the
    ambiguity note when the bare name is declared on several tools, then fill
    with the shortest VALID names (from the global resolvable lookup only —
    never names the validator would reject again) until the 280-character
    limit is exhausted."""

    shown = str(rejected)
    if len(shown) > 60:
        shown = shown[:57] + "..."
    prefix = "field must name a declared field; " + repr(shown) + " is unknown or ambiguous"
    if ambiguity_note:
        prefix += "; " + ambiguity_note
    budget = 280 - len(prefix) - len("; valid names: ")
    names: list[str] = []
    if budget > 0:
        for name in sorted(valid_lookup, key=len):
            step = len(name) + (2 if names else 0)
            if len(", ".join(names)) + step > budget:
                break
            names.append(name)
            if len(names) >= 24:
                break
    if names:
        return prefix + "; valid names: " + ", ".join(names)
    return prefix


def _reset_default(category: str, values: tuple[str, ...] = ()) -> object:
    """Deterministic reset default. The rendered candidate runtime scaffold
    owns the same mapping (candidate.py _default); a parity test pins the
    two copies together."""

    if category == "boolean":
        return False
    if category == "integer":
        return 0
    if category == "number":
        return 0.0
    if category == "list":
        return []
    if category == "enum":
        return values[0] if values else ""
    if category == "timestamp":
        return "1970-01-01T00:00:00Z"
    return ""


def _reset_value_map(architecture: WorldArchitecture) -> dict[int, object]:
    """Binding index -> deterministic reset value (pure category defaults).

    Mirrors the rendered runtime scaffold's _init exactly: the scaffold
    resets every result field to the category default and does NOT apply
    world_rules.initial_rules (recorded deviation from
    plan-judge-gate-semantics.md: the plan assumed world-rule overrides;
    runtime truth is defaults-only, so the gate verifies against defaults).
    """

    categories = _catalog_categories(architecture)
    values_by_field = {
        (tool.tool_index, field.name): tuple(field.values)
        for tool in architecture.tools
        for field in (*tool.argument_fields, *tool.result_fields)
    }
    expected: dict[int, object] = {}
    for binding in architecture.catalog.bindings:
        tool_index = int(binding.path[1])
        field = binding.path[2]
        category = categories[binding.index - 1]
        expected[binding.index] = _reset_default(
            category, values_by_field.get((tool_index, field), ())
        )
    return expected


def _bounded_repr(value: object, limit: int = 70) -> str:
    shown = repr(value)
    if len(shown) > limit:
        shown = shown[: limit - 3] + "..."
    return shown


def _verify_initial_rules(
    initial_rules: tuple[RuleDraft, ...], expected_reset: dict[int, object]
) -> str | None:
    """Return a bounded violation message when the task initial rules do not
    state the deterministic reset values, else None."""

    for rule_number, rule in enumerate(initial_rules):
        if rule.when:
            return (
                "initial_rules describe the fixed reset state; when must be [] "
                "(rule " + str(rule_number) + ")"
            )
        for effect in rule.effects:
            expected = expected_reset.get(effect.target_semantic_index)
            if effect.operation != "set" or effect.value != expected:
                return (
                    "initial rule effect must set the deterministic reset value "
                    + _bounded_repr(expected)
                    + " but sets "
                    + _bounded_repr(effect.value)
                )
    return None


def _tool_rule_lookup(
    tool_bindings: tuple[SemanticBinding, ...], tool: ToolSurface
) -> dict[str, int]:
    """Bare-name -> semantic index resolution for tool_semantics rules.

    Mirrors the rendered scaffold's by-name resolution: a when field is the
    ARGUMENT row when the tool declares an argument field of that name,
    otherwise the PRE_STATE row (the checker's current-state view). The old
    last-wins resolution bound state names to reset_state rows, which the
    composition checker reads as a constant - the luck-based semantics the
    Judge exposed.
    """

    argument_names = {field.name for field in tool.argument_fields}
    result_names = {field.name for field in tool.result_fields}
    lookup: dict[str, int] = {}
    for binding in tool_bindings:
        if binding.source == "argument" and binding.name in argument_names:
            lookup[binding.name] = binding.index
        elif binding.source == "pre_state" and binding.name in result_names:
            lookup.setdefault(binding.name, binding.index)
    return lookup


def _transition_when_key(rule: RuleDraft) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        sorted(
            (
                predicate.left_semantic_index,
                predicate.operator,
                json.dumps(predicate.right, sort_keys=True, ensure_ascii=False, default=str),
            )
            for predicate in rule.when
        )
    )


def _reject_transition_degeneracy(
    transitions: tuple[RuleDraft, ...],
    tool_bindings: tuple[SemanticBinding, ...],
    tool: ToolSurface,
) -> None:
    """Reject degenerate transition sets before they reach the Judge:

    - two transitions with IDENTICAL when conditions (the later one silently
      overwrites the earlier one - ambiguous semantics);
    - a when predicate on a state field no transition ever changes (the
      condition can never vary; an unconditional rule must use an empty when);
    - an effect targeting an argument field (the scaffold mutates state
      fields only; such an effect can never satisfy the composition check).
    """

    binding_by_index = {binding.index: binding for binding in tool_bindings}
    seen: dict[tuple[tuple[int, str, str], ...], int] = {}
    for number, rule in enumerate(transitions):
        key = _transition_when_key(rule)
        if key in seen:
            raise DesignError(
                "tool_semantics_invalid",
                path="$.transitions[" + str(number) + "]",
                violated_condition=(
                    "transitions with identical when conditions are ambiguous: "
                    "transitions["
                    + str(seen[key])
                    + "] and transitions["
                    + str(number)
                    + "] fire together and the last one wins; merge them into "
                    "one rule or differentiate the conditions"
                ),
                expected_category="array",
            )
        seen[key] = number
    result_names = {field.name for field in tool.result_fields}
    mutated_names = {
        binding_by_index[effect.target_semantic_index].name
        for rule in transitions
        for effect in rule.effects
        if effect.operation not in {"preserve", "reject"}
        and effect.target_semantic_index in binding_by_index
    }
    for number, rule in enumerate(transitions):
        for predicate in rule.when:
            binding = binding_by_index.get(predicate.left_semantic_index)
            if binding is None or binding.source == "argument":
                continue
            if binding.name not in mutated_names:
                raise DesignError(
                    "tool_semantics_invalid",
                    path="$.transitions[" + str(number) + "].when",
                    violated_condition=(
                        "when references state field '"
                        + binding.name
                        + "' which no transition ever changes; the condition "
                        "can never vary - reference a changed field or use an "
                        "empty when"
                    ),
                    expected_category="semantic_draft",
                )
        for effect in rule.effects:
            target = binding_by_index.get(effect.target_semantic_index)
            if target is not None and target.name not in result_names:
                raise DesignError(
                    "tool_semantics_invalid",
                    path="$.transitions[" + str(number) + "].effects",
                    violated_condition=(
                        "effects may only change state (result) fields, never "
                        "argument field '"
                        + target.name
                        + "'"
                    ),
                    expected_category="semantic_draft",
                )


def _simulate_trace(
    family_tool_indexes: tuple[int, ...],
    tools: tuple[ToolDraft, ...],
    reset_state: dict[str, dict[str, object]],
) -> tuple[dict[str, Any], bool]:
    """Full synthetic trace (argument/tool_result/pre_state/post_state/
    reset_state per tool) for the recipe action sequence (primary difficulty,
    guard-satisfying arguments). Mirrors the runtime composition checker's
    transition application exactly."""

    trace: dict[str, dict[str, Any]] = {
        "argument": {},
        "tool_result": {},
        "pre_state": {},
        "post_state": {},
        "reset_state": {},
    }
    state = {name: dict(values) for name, values in reset_state.items()}
    failed = False
    for index in family_tool_indexes:
        tool = tools[index - 1]
        arguments = {field.name: _value(field) for field in tool.surface.argument_fields}
        arguments = _guard_arguments(tool, arguments)
        before = dict(state[tool.surface.name])
        for rule in tool.transitions:
            view = {
                "argument": {str(index): arguments},
                "tool_result": {str(index): state[tool.surface.name]},
                "pre_state": {str(index): state[tool.surface.name]},
                "post_state": {str(index): state[tool.surface.name]},
                "reset_state": {str(index): reset_state[tool.surface.name]},
            }
            if not _predicates(rule, tool.bindings, view):
                continue
            for effect in rule.effects:
                target = tool.bindings[effect.target_semantic_index - 1]
                current = state[tool.surface.name]
                if effect.operation == "reject":
                    failed = True
                elif effect.operation == "preserve":
                    continue
                elif effect.operation == "set":
                    current[target.name] = effect.value
                elif effect.operation == "increment":
                    current[target.name] = current[target.name] + effect.value
                elif effect.operation == "decrement":
                    current[target.name] = current[target.name] - effect.value
                elif effect.operation == "add":
                    current[target.name] = current[target.name] + [effect.value]
                elif effect.operation == "remove":
                    current[target.name] = [
                        item for item in current[target.name] if item != effect.value
                    ]
        index_str = str(index)
        trace["argument"][index_str] = arguments
        trace["tool_result"][index_str] = state[tool.surface.name]
        trace["pre_state"][index_str] = before
        trace["post_state"][index_str] = state[tool.surface.name]
        trace["reset_state"][index_str] = reset_state[tool.surface.name]
    return trace, failed


def _verify_family_outcome(
    family_tool_indexes: tuple[int, ...],
    tools: tuple[ToolDraft, ...],
    architecture: WorldArchitecture,
    success_rules: tuple[RuleDraft, ...],
    failure_rules: tuple[RuleDraft, ...],
) -> str | None:
    """Simulate the recipe baseline and require a success pattern to hold.
    Returns a bounded correction message when the Judge's
    terminal_success_reward_plus_one condition cannot be met; the Judge
    remains the only release authority."""

    reset_map = _reset_value_map(architecture)
    reset_state: dict[str, dict[str, object]] = {}
    for tool in tools:
        values: dict[str, object] = {}
        for binding in architecture.catalog.bindings:
            if binding.source == "reset_state" and binding.path[1] == str(tool.tool_index):
                values[binding.name] = reset_map[binding.index]
        reset_state[tool.surface.name] = values
    try:
        trace, failed = _simulate_trace(family_tool_indexes, tools, reset_state)
    except Exception as exc:  # the simulation must never crash the node
        return "design-time simulation failed internally: " + _bounded_repr(str(exc))
    if failed:
        return (
            "design-time simulation: a reject effect fired on the success "
            "trace; the task cannot reach terminal success"
        )
    bindings = _task_bindings(tools)
    success = any(_predicates(rule, bindings, trace) for rule in success_rules)
    failure = any(_predicates(rule, bindings, trace) for rule in failure_rules)
    if failure:
        return (
            "design-time simulation: a failure pattern holds after the action "
            "sequence; the Judge requires a success pattern (reward +1); "
            "success rules hold: False; failure rules hold: True"
        )
    if not success:
        pieces: list[str] = []
        for rule in success_rules:
            parts = []
            for predicate in rule.when:
                binding = bindings[predicate.left_semantic_index - 1]
                tool_name = tools[int(binding.path[1]) - 1].surface.name
                held = _predicates(
                    RuleDraft((predicate,), (), None, "", ()), bindings, trace
                )
                parts.append(
                    tool_name + "." + binding.name + " " + predicate.operator
                    + "=" + str(held)
                )
            pieces.append("[" + ", ".join(parts) + "]")
        pattern_text = " ".join(pieces)
        if len(pattern_text) > 170:
            pattern_text = pattern_text[:167] + "..."
        return (
            "design-time simulation: no success pattern holds after the action "
            "sequence; success predicate checks: "
            + pattern_text
        )
    return None


def _compile_rules(
    value: object,
    bindings: tuple[SemanticBinding, ...],
    citations: set[int],
    code: str,
    *,
    path: str,
    minimum: int,
    maximum: int,
    errors_only: bool | None = None,
    effects_min: int = 1,
    effects_max: int = 6,
    effects_violation: str | None = None,
    lookup: dict[str, int] | None = None,
) -> tuple[RuleDraft, ...]:
    """Compile LLM-format rules (field-name based) into internal RuleDrafts.

    The LLM outputs predicates/effects with ``field`` (a NAME from the binding
    catalog) instead of ``left_semantic_index``/``target_semantic_index``.  This
    function resolves each name to its frozen one-based index and constructs
    PredicateDraft/EffectDraft identical to the old compile path so that the
    committed artifact remains byte-identical.
    """

    if lookup is None:
        lookup = _name_to_index(bindings)
    result: list[RuleDraft] = []
    for number, raw_rule in enumerate(_array(value, minimum, maximum, code, path=path)):
        item_path = f"{path}[{number}]"
        raw = _object(raw_rule, _RULE_KEYS, code, path=item_path)
        predicates: list[PredicateDraft] = []
        for predicate_number, raw_predicate in enumerate(
            _array(raw["when"], 0, 6, code, path=f"{item_path}.when")
        ):
            predicate_path = f"{item_path}.when[{predicate_number}]"
            if not isinstance(raw_predicate, dict):
                raise DesignError(
                    code,
                    path=predicate_path,
                    violated_condition="predicate must be an object",
                    expected_category="object",
                )
            operator = raw_predicate.get("operator")
            is_existence = operator in _EXISTENCE_OPERATORS
            expected = {"field", "operator"} if is_existence else {"field", "operator", "value"}
            if set(raw_predicate) != expected:
                raise DesignError(
                    code,
                    path=predicate_path,
                    violated_condition=(
                        "predicate must contain exactly these fields and no others: "
                        + ", ".join(sorted(expected))
                    ),
                    expected_category="object",
                )
            field_name = raw_predicate["field"]
            if not isinstance(field_name, str) or field_name not in lookup:
                raise DesignError(
                    code,
                    path=f"{predicate_path}.field",
                    violated_condition=f"field must name a declared field; unknown field {field_name!r}",  # noqa: E501
                    expected_category="string",
                )
            if operator not in _PREDICATE_OPERATORS:
                raise DesignError(
                    code,
                    path=f"{predicate_path}.operator",
                    violated_condition=(
                        "operator must be one of "
                        "eq|ne|lt|le|gt|ge|contains|not_contains|exists|not_exists"
                    ),
                    expected_category="string",
                )
            if is_existence:
                right: Any = None
            else:
                raw_value = raw_predicate["value"]
                if not _json_value(raw_value):
                    raise DesignError(
                        code,
                        path=f"{predicate_path}.value",
                        violated_condition=(
                            "value must be a JSON scalar or scalar-list of at most 32 items"
                        ),
                        expected_category="semantic_draft",
                    )
                right = raw_value
            predicates.append(PredicateDraft(lookup[field_name], cast(Any, operator), right))
        effects: list[EffectDraft] = []
        if effects_violation is not None and raw["effects"]:
            raise DesignError(
                code,
                path=f"{item_path}.effects",
                violated_condition=effects_violation,
                expected_category="array",
            )
        for effect_number, raw_effect in enumerate(
            _array(raw["effects"], effects_min, effects_max, code, path=f"{item_path}.effects")
        ):
            effect_path = f"{item_path}.effects[{effect_number}]"
            if not isinstance(raw_effect, dict):
                raise DesignError(
                    code,
                    path=effect_path,
                    violated_condition="effect must be an object",
                    expected_category="object",
                )
            operation = raw_effect.get("operation")
            is_no_value = operation in _NO_VALUE_OPERATIONS
            expected = {"field", "operation"} if is_no_value else {"field", "operation", "value"}
            if set(raw_effect) != expected:
                raise DesignError(
                    code,
                    path=effect_path,
                    violated_condition=(
                        "effect must contain exactly these fields and no others: "
                        + ", ".join(sorted(expected))
                    ),
                    expected_category="object",
                )
            field_name = raw_effect["field"]
            if not isinstance(field_name, str) or field_name not in lookup:
                raise DesignError(
                    code,
                    path=f"{effect_path}.field",
                    violated_condition=f"field must name a declared field; unknown field {field_name!r}",  # noqa: E501
                    expected_category="string",
                )
            if operation not in _EFFECT_OPERATIONS:
                raise DesignError(
                    code,
                    path=f"{effect_path}.operation",
                    violated_condition=(
                        "operation must be one of "
                        "set|increment|decrement|add|remove|preserve|reject"
                    ),
                    expected_category="string",
                )
            if is_no_value:
                effect_value: Any = None
            else:
                effect_value = raw_effect["value"]
                if not _json_value(effect_value):
                    raise DesignError(
                        code,
                        path=f"{effect_path}.value",
                        violated_condition=(
                            "value must be a JSON scalar or scalar-list of at most 32 items"
                        ),
                        expected_category="semantic_draft",
                    )
            effects.append(EffectDraft(lookup[field_name], cast(Any, operation), effect_value))
        error_kind = raw["error_kind"]
        if errors_only is True and (
            not isinstance(error_kind, str) or not _NAME.fullmatch(error_kind)
        ):
            raise DesignError(
                code,
                path=f"{item_path}.error_kind",
                violated_condition="error rules require a bounded error kind",
                expected_category="string",
            )
        if errors_only is False and error_kind is not None:
            raise DesignError(
                code,
                path=f"{item_path}.error_kind",
                violated_condition="non-error rules require null error_kind",
                expected_category="string",
            )
        cited = _array(raw["citation_indexes"], 0, 8, code, path=f"{item_path}.citation_indexes")
        if any(type(item) is not int or item not in citations for item in cited) or len(
            set(cited)
        ) != len(cited):
            raise DesignError(
                code,
                path=f"{item_path}.citation_indexes",
                violated_condition="citations must be unique frozen citation indexes",
                expected_category="array",
            )
        result.append(
            RuleDraft(
                tuple(predicates),
                tuple(effects),
                cast(Any, error_kind),
                _text(raw["rationale"], code, 300, path=f"{item_path}.rationale"),
                tuple(cited),
            )
        )
    return tuple(result)


def _compile_task_rules(
    value: object,
    bindings: tuple[SemanticBinding, ...],
    citations: set[int],
    *,
    path: str,
    minimum: int,
    maximum: int,
    effects_min: int = 1,
    effects_max: int = 6,
    effects_violation: str | None = None,
    lookup: dict[str, int] | None = None,
) -> tuple[RuleDraft, ...]:
    """Compile the TaskRequirement-only non-error source shape.

    The model cannot supply the framework-owned non-error value.  Source
    validation remains closed before an internal copy restores the generic
    compiler input expected by the committed RuleDraft contract.
    """

    internal_rules: list[dict[str, Any]] = []
    for number, source_rule in enumerate(
        _array(value, minimum, maximum, "task_requirement_invalid", path=path)
    ):
        source = _object(
            source_rule,
            _TASK_RULE_KEYS,
            "task_requirement_invalid",
            path=f"{path}[{number}]",
        )
        internal_rules.append({**source, "error_kind": None})
    return _compile_rules(
        internal_rules,
        bindings,
        citations,
        "task_requirement_invalid",
        path=path,
        minimum=minimum,
        maximum=maximum,
        errors_only=False,
        effects_min=effects_min,
        effects_max=effects_max,
        effects_violation=effects_violation,
        lookup=lookup,
    )


def _reject_guard_conflicts(rules: tuple[RuleDraft, ...], code: str) -> None:
    """Precondition guards are AND-ed: reject jointly unsatisfiable eq pairs."""

    eq_values: dict[int, object] = {}
    for number, rule in enumerate(rules):
        for predicate in rule.when:
            if predicate.operator != "eq":
                continue
            index = predicate.left_semantic_index
            if index in eq_values and eq_values[index] != predicate.right:
                raise DesignError(
                    code,
                    path=f"$.preconditions[{number}].when",
                    violated_condition=(
                        "precondition guards are AND-ed and must be jointly "
                        "satisfiable; express alternatives as transitions, not as "
                        "multiple eq guards on one field"
                    ),
                    expected_category="array",
                )
            eq_values[index] = predicate.right


def _effect_category_ok(
    field_category: str, field_values: list[Any], effect: EffectDraft
) -> tuple[bool, str]:
    """Verify an effect value matches its target field category."""

    value = effect.value
    if effect.operation in {"preserve", "reject"}:
        return True, ""
    if effect.operation in {"increment", "decrement"}:
        if field_category not in {"integer", "number"}:
            return False, (
                "target field category " + field_category
                + " does not accept " + effect.operation
            )
        if type(value) not in {int, float} or (
            type(value) is float and not math.isfinite(value)
        ):
            return False, "numeric effect value required"
        return True, ""
    if effect.operation in {"add", "remove"}:
        if field_category != "list":
            return False, (
                "target field category " + field_category
                + " does not accept " + effect.operation
            )
        return True, ""
    if field_category == "list":
        if not isinstance(value, list):
            return False, (
                "field is declared list but set receives a "
                + type(value).__name__ + "; use add with a scalar item or set with a list"
            )
        return True, ""
    if field_category == "boolean":
        return type(value) is bool, "boolean value required"
    if field_category == "integer":
        return type(value) is int and not isinstance(value, bool), "integer value required"
    if field_category == "number":
        return (
            type(value) in {int, float}
            and not isinstance(value, bool)
            and not (type(value) is float and not math.isfinite(value))
        ), "number value required"
    if field_category in {"text", "timestamp", "identifier"}:
        return type(value) is str, "string value required"
    if field_category == "enum":
        return (
            isinstance(value, str) and value in field_values
        ), ("enum value must be one of " + repr(field_values))
    return True, ""


def _binding_fields_for_llm(
    bindings: tuple[SemanticBinding, ...],
    architecture: WorldArchitecture,
) -> list[dict[str, str]]:
    """Project bindings as readable field rows — no indices, no path tuples."""

    tool_name: dict[int, str] = {tool.tool_index: tool.name for tool in architecture.tools}
    category: dict[tuple[int, str], str] = {}
    for tool in architecture.tools:
        for field in (*tool.argument_fields, *tool.result_fields):
            category[(tool.tool_index, field.name)] = field.category
    return [
        {
            "source": binding.source,
            "tool": tool_name.get(int(binding.path[1]), f"tool_{binding.path[1]}"),
            "field": binding.name,
            "category": category.get((int(binding.path[1]), binding.name), "json_value"),
        }
        for binding in bindings
    ]


def _task_semantic_fields(architecture: WorldArchitecture) -> list[dict[str, Any]]:
    """Task-requirement projection rows: the shared field rows plus the
    deterministic reset_value on every reset_state row (scoped here so the
    four-consumer shared helper stays unchanged)."""

    rows = _binding_fields_for_llm(architecture.catalog.bindings, architecture)
    reset_map = _reset_value_map(architecture)
    tool_name = {tool.tool_index: tool.name for tool in architecture.tools}
    reset_by_key: dict[tuple[str, str], object] = {}
    for binding in architecture.catalog.bindings:
        if binding.source == "reset_state":
            reset_by_key[(tool_name[int(binding.path[1])], binding.name)] = reset_map[
                binding.index
            ]
    for row in rows:
        if row["source"] == "reset_state":
            row["reset_value"] = reset_by_key.get((row["tool"], row["field"]))
    return rows


def _predicate_for_llm(
    pred: PredicateDraft,
    index_to_name: dict[int, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "field": index_to_name.get(pred.left_semantic_index, "?"),
        "operator": pred.operator,
    }
    if pred.operator not in _EXISTENCE_OPERATORS:
        result["value"] = pred.right
    return result


def _effect_for_llm(
    effect: EffectDraft,
    index_to_name: dict[int, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "field": index_to_name.get(effect.target_semantic_index, "?"),
        "operation": effect.operation,
    }
    if effect.operation not in _NO_VALUE_OPERATIONS:
        result["value"] = effect.value
    return result


def _rules_for_llm(
    rules: tuple[RuleDraft, ...],
    bindings: tuple[SemanticBinding, ...],
) -> list[dict[str, Any]]:
    """Project compiled RuleDrafts into the readable field-name format."""

    index_to_name = {binding.index: binding.name for binding in bindings}
    result: list[dict[str, Any]] = []
    for rule in rules:
        projected: dict[str, Any] = {
            "when": [_predicate_for_llm(pred, index_to_name) for pred in rule.when],
            "effects": [_effect_for_llm(eff, index_to_name) for eff in rule.effects],
            "rationale": rule.rationale,
            "citation_indexes": list(rule.citation_indexes),
        }
        if rule.error_kind is not None:
            projected["error_kind"] = rule.error_kind
        result.append(projected)
    return result


def _tools_rules_for_llm(
    tools: tuple[ToolDraft, ...],
    indexes: tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    """Project tool preconditions/transitions/postconditions/errors readably."""

    selected = tools if indexes is None else [tools[i - 1] for i in indexes]
    return [
        {
            "name": tool.surface.name,
            "preconditions": _rules_for_llm(tool.preconditions, tool.bindings),
            "transitions": _rules_for_llm(tool.transitions, tool.bindings),
            "postconditions": _rules_for_llm(tool.postconditions, tool.bindings),
            "errors": _rules_for_llm(tool.errors, tool.bindings),
        }
        for tool in selected
    ]


def _catalog(architecture: WorldArchitecture) -> tuple[SemanticBinding, ...]:
    bindings: list[SemanticBinding] = []
    for tool in architecture.tools:
        for source, fields in (
            ("argument", tool.argument_fields),
            ("tool_result", tool.result_fields),
            ("pre_state", tool.result_fields),
            ("post_state", tool.result_fields),
            ("reset_state", tool.result_fields),
        ):
            for field in fields:
                bindings.append(
                    SemanticBinding(
                        len(bindings) + 1,
                        cast(Any, source),
                        field.name,
                        (source, str(tool.tool_index), field.name),
                    )
                )
    return tuple(bindings)


def _catalog_categories(architecture: WorldArchitecture) -> tuple[str, ...]:
    return tuple(
        field.category
        for tool in architecture.tools
        for fields in (
            tool.argument_fields,
            tool.result_fields,
            tool.result_fields,
            tool.result_fields,
            tool.result_fields,
        )
        for field in fields
    )


class DesignExecutor:
    def __init__(
        self, settings: FoundrySettings, direct: DirectChatBackend, agent: CodexAgentBackend
    ) -> None:
        self.settings, self.direct, self.agent = settings, direct, agent

    def _agent_json(
        self,
        work: str,
        skill: str,
        workspace: Path,
        instruction: str,
        correction: CorrectionPacket | None = None,
    ) -> InvocationResult:
        if correction is not None:
            instruction += (
                "\nAuthorized correction packet: " + _canonical(json_value(correction)).decode()
            )
        try:
            return self.agent.invoke_json(
                work=work, skill_name=skill, workspace=workspace, instruction=instruction
            )
        except InvocationError as exc:
            raise DesignError(
                exc.failure.code, exc.failure.status, exc.failure.retryable, correctable=False
            ) from exc

    def _direct_json(
        self,
        node: str,
        projection: dict[str, Any],
        shape: str,
        correction: CorrectionPacket | None = None,
        *,
        previous_output: str | None = None,
    ) -> InvocationResult | _DirectFormatFailure:
        system = (
            f"You are Direct semantic node {node}. You have no tools, Skills, workspace, "
            "or release authority. Return exactly one JSON object matching the disclosed shape."
        )
        if correction is not None and previous_output is None:
            raise DesignError("direct_feedback_unavailable", correctable=False)
        user = _canonical(
            {
                "node": node,
                "input": projection,
                "output_shape": shape,
                "correction": None,
            }
        ).decode()
        try:
            return self.direct.invoke_json(
                system=system,
                user=user,
                previous_assistant=previous_output if correction is not None else None,
                feedback=_direct_feedback(correction) if correction is not None else None,
            )
        except InvocationError as exc:
            raise DesignError(
                exc.failure.code, exc.failure.status, exc.failure.retryable, correctable=False
            ) from exc

    @staticmethod
    def _model_evidence(
        category: Literal["direct_llm", "agent"],
        node: str,
        result: InvocationResult | _DirectFormatFailure,
    ) -> tuple[OperationEvidence, ...]:
        return (
            OperationEvidence(
                category,
                node,
                result.route_model,
                result.usage,
                result.skill_digest if isinstance(result, InvocationResult) else None,
            ),
        )

    def _direct_commit(
        self,
        node: str,
        projection: dict[str, Any],
        shape: str,
        kind: str,
        compiler: Callable[[dict[str, Any]], Any],
        inputs: dict[str, tuple[ArtifactRef, ...]],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        *,
        shard_key: str | None = None,
        output_type: Any = None,
    ) -> tuple[Any, ArtifactRef, ArtifactRef]:
        visible_projection = _model_value(projection)
        previous_output: str | None = None

        def operation(
            correction: CorrectionPacket | None,
        ) -> InvocationResult | _DirectFormatFailure:
            nonlocal previous_output
            result = self._direct_json(
                node,
                visible_projection,
                shape,
                correction,
                previous_output=previous_output,
            )
            if isinstance(result, _DirectFormatFailure):
                previous_output = result.raw_content
            else:
                previous_output = _canonical(result.value).decode()
            return result

        def compile(result: InvocationResult | _DirectFormatFailure) -> Any:
            if isinstance(result, _DirectFormatFailure):
                raise DesignError(
                    "direct_response_not_json",
                    path="$",
                    violated_condition=result.condition.violated_condition(),
                    expected_category="object",
                )
            if not isinstance(result.value, dict):
                raise DesignError(
                    f"{node}_invalid",
                    path="$",
                    violated_condition="proposal must be a JSON object",
                    expected_category="object",
                )
            return compiler(result.value)

        node_result = graph.execute(
            store,
            run_id,
            node,
            inputs,
            kind,
            operation,
            compile,
            {
                "effective_projection": visible_projection,
                "output_shape": shape,
                "prompt_identity": graph.node(node).prompt_id,
            },
            artifact_projection=json_value,
            operation_evidence=lambda result: self._model_evidence("direct_llm", node, result),
            shard_key=shard_key,
            output_type=output_type,
        )
        return node_result.value, node_result.artifact, node_result.work

    def _research_plan(
        self,
        request: EnvironmentRequest,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
    ) -> tuple[ResearchPlan, ArtifactRef, ArtifactRef]:
        def operation(correction: CorrectionPacket | None) -> InvocationResult:
            with tempfile.TemporaryDirectory(prefix="foundry-research-plan-") as temporary:
                workspace = Path(temporary)
                (workspace / "request.json").write_bytes(_canonical({"need": request.need}))
                return self._agent_json(
                    "research_plan",
                    "research-world-evidence",
                    workspace,
                    "Read request.json. Return ResearchPlanDraft exactly: "
                    "{queries:[text] (1..6),questions_to_resolve:[text] (1..12)}.",
                    correction,
                )

        def compile(result: InvocationResult) -> ResearchPlan:
            value = _object(
                result.value,
                {"queries", "questions_to_resolve"},
                "research_plan_invalid",
            )
            queries = tuple(
                _text(item, "research_plan_invalid", 240, path=f"$.queries[{index}]")
                for index, item in enumerate(
                    _array(value["queries"], 1, 6, "research_plan_invalid", path="$.queries")
                )
            )
            questions = tuple(
                _text(item, "research_plan_invalid", 240, path=f"$.questions_to_resolve[{index}]")
                for index, item in enumerate(
                    _array(
                        value["questions_to_resolve"],
                        1,
                        12,
                        "research_plan_invalid",
                        path="$.questions_to_resolve",
                    )
                )
            )
            return ResearchPlan(queries, questions, _PENDING)

        node = graph.execute(
            store,
            run_id,
            "research_plan",
            {"request": (request_ref,)},
            "design.research_plan",
            operation,
            compile,
            {"request_digest": request.need_digest, "output_shape": "ResearchPlanDraft@1"},
            artifact_projection=lambda value: json_value(replace(value, artifact=_PENDING)),
            operation_evidence=lambda result: self._model_evidence(
                "agent", "research_plan", result
            ),
            output_type=ResearchPlan,
        )
        return replace(node.value, artifact=node.artifact), node.artifact, node.work

    def _http_text(self, url: str, *, key: str | None, stage: str) -> str:
        headers = {
            "Accept": "text/plain,text/markdown,text/html",
            "User-Agent": "agent-world-foundry/0.3",
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with urlopen(Request(url, headers=headers), timeout=120) as response:  # noqa: S310
                body = response.read()
        except HTTPError as exc:
            raise DesignError(
                f"{stage}_http_failure", "error", exc.code in {408, 429, 500, 502, 503, 504}
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DesignError(f"{stage}_network_failure", "error", True) from exc
        if not (text := body.decode("utf-8", errors="replace").strip()):
            raise DesignError(f"{stage}_empty")
        return text

    def _research_acquire(
        self,
        plan: ResearchPlan,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        plan_ref: ArtifactRef,
    ) -> tuple[tuple[dict[str, Any], ...], ArtifactRef, ArtifactRef]:
        try:
            key = credential_from_environment(self.settings.research.api_key_env)
        except ConfigurationError as exc:
            raise DesignError(str(exc), "needs_human") from exc

        def operation(
            _: CorrectionPacket | None,
        ) -> tuple[list[dict[str, Any]], list[str], tuple[OperationEvidence, ...]]:
            commitments: list[dict[str, Any]] = []
            texts: list[str] = []
            operations: list[OperationEvidence] = []
            for query in plan.queries:
                search = self._http_text(
                    f"{self.settings.research.search_url}/{quote(query, safe='')}",
                    key=key,
                    stage="research_search",
                )
                operations.append(OperationEvidence("search", "research_acquire", None, None))
                for url in _source_urls(search):
                    text = self._http_text(
                        f"{self.settings.research.reader_url}/{url}",
                        key=key,
                        stage="research_fetch",
                    )
                    encoded = text.encode()
                    commitments.append(
                        {
                            "url": safe_url(url),
                            "content_digest": "sha256:" + sha256(encoded).hexdigest(),
                            "content_length": len(encoded),
                        }
                    )
                    texts.append(text[:10000])
                    operations.extend(
                        (
                            OperationEvidence("fetch", "research_acquire", None, None),
                            OperationEvidence("extract", "research_acquire", None, None),
                        )
                    )
                    if len(commitments) == 6:
                        break
                if len(commitments) == 6:
                    break
            if not commitments:
                raise DesignError("research_no_provenance_sources")
            return commitments, texts, tuple(operations)

        node = graph.execute(
            store,
            run_id,
            "research_acquire",
            {"research_plan": (plan_ref,)},
            "design.research_acquire",
            operation,
            lambda value: value,
            {"research_plan": plan_ref.digest, "output_shape": "ResearchAcquisition@1"},
            artifact_projection=lambda value: {
                "sources": value[0],
                "citation_catalog": [
                    {"index": index, "url": item["url"]} for index, item in enumerate(value[0], 1)
                ],
            },
            operation_evidence=lambda value: value[2],
            output_type=tuple[list[dict[str, Any]], list[str], tuple[OperationEvidence, ...]],
        )
        return (
            tuple(
                {**commitment, "text": node.value[1][index]}
                for index, commitment in enumerate(node.value[0])
            ),
            node.artifact,
            node.work,
        )

    def _research_synthesis(
        self,
        request: EnvironmentRequest,
        plan: ResearchPlan,
        sources: tuple[dict[str, Any], ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
        plan_ref: ArtifactRef,
        acquire_ref: ArtifactRef,
    ) -> tuple[EvidenceGraph, ArtifactRef, ArtifactRef]:
        def operation(correction: CorrectionPacket | None) -> InvocationResult:
            with tempfile.TemporaryDirectory(prefix="foundry-research-synthesis-") as temporary:
                workspace = Path(temporary)
                (workspace / "evidence.json").write_bytes(
                    _canonical(
                        {
                            "request": request.need,
                            "questions": plan.questions_to_resolve,
                            "citations": [
                                {"index": index, "url": source["url"], "text": source["text"]}
                                for index, source in enumerate(sources, 1)
                            ],
                        }
                    )
                )
                return self._agent_json(
                    "research_synthesis",
                    "research-world-evidence",
                    workspace,
                    "Read evidence.json. Return ResearchSynthesisDraft exactly: claims/conflicts "
                    "arrays of {statement,kind:observed|bounded_inference,citation_indexes}, "
                    "and gaps:[text]. Claims 1..32 and every claim citation is one-based "
                    "from the staged catalog.",
                    correction,
                )

        def claim(raw: object, path: str) -> EvidenceClaim:
            value = _object(
                raw,
                {"statement", "kind", "citation_indexes"},
                "research_synthesis_invalid",
                path=path,
            )
            indexes = _array(
                value["citation_indexes"],
                1,
                6,
                "research_synthesis_invalid",
                path=f"{path}.citation_indexes",
            )
            if (
                value["kind"] not in {"observed", "bounded_inference"}
                or len(set(indexes)) != len(indexes)
                or any(type(item) is not int or not 1 <= item <= len(sources) for item in indexes)
            ):
                raise DesignError(
                    "research_synthesis_invalid",
                    path=path,
                    violated_condition="claim kind and citations must be from the frozen catalog",
                    expected_category="object",
                )
            return EvidenceClaim(
                _text(
                    value["statement"], "research_synthesis_invalid", 500, path=f"{path}.statement"
                ),
                cast(Any, value["kind"]),
                tuple(indexes),
            )

        def compile(result: InvocationResult) -> EvidenceGraph:
            value = _object(
                result.value, {"claims", "conflicts", "gaps"}, "research_synthesis_invalid"
            )
            claims = tuple(
                claim(item, f"$.claims[{index}]")
                for index, item in enumerate(
                    _array(value["claims"], 1, 32, "research_synthesis_invalid", path="$.claims")
                )
            )
            conflicts = tuple(
                claim(item, f"$.conflicts[{index}]")
                for index, item in enumerate(
                    _array(
                        value["conflicts"], 0, 16, "research_synthesis_invalid", path="$.conflicts"
                    )
                )
            )
            gaps = tuple(
                _text(item, "research_synthesis_invalid", 300, path=f"$.gaps[{index}]")
                for index, item in enumerate(
                    _array(value["gaps"], 0, 16, "research_synthesis_invalid", path="$.gaps")
                )
            )
            catalog = CitationCatalog(
                tuple(
                    CitationCatalogItem(
                        index, f"source-{index}", source["url"], source["text"][:500]
                    )
                    for index, source in enumerate(sources, 1)
                )
            )
            return EvidenceGraph(claims, conflicts, gaps, catalog, _PENDING)

        node = graph.execute(
            store,
            run_id,
            "research_synthesis",
            {
                "request": (request_ref,),
                "research_plan": (plan_ref,),
                "sources": (acquire_ref,),
                "citations": (acquire_ref,),
            },
            "design.evidence_graph",
            operation,
            compile,
            {
                "request_digest": request.need_digest,
                "questions_to_resolve": plan.questions_to_resolve,
                "citation_catalog": [
                    {
                        "index": index,
                        "url": source["url"],
                        "content_digest": source["content_digest"],
                    }
                    for index, source in enumerate(sources, 1)
                ],
                "output_shape": "ResearchSynthesisDraft@1",
            },
            artifact_projection=lambda value: json_value(replace(value, artifact=_PENDING)),
            operation_evidence=lambda result: self._model_evidence(
                "agent", "research_synthesis", result
            ),
            output_type=EvidenceGraph,
        )
        return replace(node.value, artifact=node.artifact), node.artifact, node.work

    def _direct_architecture(
        self,
        request: EnvironmentRequest,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        request_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[WorldArchitecture, ArtifactRef, ArtifactRef]:
        citations = {item.index for item in evidence.catalog.items}

        def compile(value: dict[str, Any]) -> WorldArchitecture:
            raw = _object(
                value,
                {"boundary", "entities", "tools", "known_divergences"},
                "world_architecture_invalid",
            )

            def field_array(
                value: object, minimum: int, *, path: str
            ) -> tuple[FieldDeclaration, ...]:
                fields = tuple(
                    _field(
                        field,
                        "world_architecture_invalid",
                        path=f"{path}[{field_index}]",
                    )
                    for field_index, field in enumerate(
                        _array(value, minimum, 24, "world_architecture_invalid", path=path)
                    )
                )
                if len({field.name for field in fields}) != len(fields):
                    raise DesignError(
                        "world_architecture_invalid",
                        path=path,
                        violated_condition="field names must be unique within their owner",
                        expected_category="array",
                    )
                return fields

            boundary_value = _object(
                raw["boundary"],
                {"name", "purpose", "system_of_record", "authority", "actors"},
                "world_architecture_invalid",
                path="$.boundary",
            )
            actors = tuple(
                _text(item, "world_architecture_invalid", 80, path=f"$.boundary.actors[{index}]")
                for index, item in enumerate(
                    _array(
                        boundary_value["actors"],
                        1,
                        8,
                        "world_architecture_invalid",
                        path="$.boundary.actors",
                    )
                )
            )
            if len(set(actors)) != len(actors):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.boundary.actors",
                    violated_condition="actors must be unique",
                    expected_category="array",
                )
            boundary_name = _text(
                boundary_value["name"],
                "world_architecture_invalid",
                160,
                path="$.boundary.name",
            )
            purpose = boundary_value["purpose"]
            boundary_purpose = purpose.strip() if isinstance(purpose, str) else ""
            if not boundary_purpose or len(boundary_purpose) > 4096:
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.boundary.purpose",
                    violated_condition=(
                        "value must be text with nonempty content after stripping"
                        if not boundary_purpose
                        else "stripped value must contain at most 4096 Unicode code points"
                    ),
                    expected_category="string",
                )
            system_of_record = _text(
                boundary_value["system_of_record"],
                "world_architecture_invalid",
                160,
                path="$.boundary.system_of_record",
            )
            authority = _text(
                boundary_value["authority"],
                "world_architecture_invalid",
                160,
                path="$.boundary.authority",
            )
            boundary = WorldBoundary(
                boundary_name, boundary_purpose, system_of_record, authority, actors
            )
            entities: list[EntityDeclaration] = []
            for index, item in enumerate(
                _array(raw["entities"], 1, 16, "world_architecture_invalid", path="$.entities")
            ):
                entity = _object(
                    item,
                    {"name", "purpose", "fields"},
                    "world_architecture_invalid",
                    path=f"$.entities[{index}]",
                )
                fields = field_array(entity["fields"], 1, path=f"$.entities[{index}].fields")
                entities.append(
                    EntityDeclaration(
                        _text(
                            entity["name"],
                            "world_architecture_invalid",
                            64,
                            path=f"$.entities[{index}].name",
                        ),
                        _text(
                            entity["purpose"],
                            "world_architecture_invalid",
                            300,
                            path=f"$.entities[{index}].purpose",
                        ),
                        fields,
                    )
                )
            entity_names = {entity.name for entity in entities}
            if len(entity_names) != len(entities) or any(
                field.entity_ref and field.entity_ref not in entity_names
                for entity in entities
                for field in entity.fields
            ):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.entities",
                    violated_condition="entity names and references must be closed",
                    expected_category="array",
                )
            tools: list[ToolSurface] = []
            for index, item in enumerate(
                _array(raw["tools"], 1, 8, "world_architecture_invalid", path="$.tools")
            ):
                tool = _object(
                    item,
                    {"name", "purpose", "actor_names", "argument_fields", "result_fields"},
                    "world_architecture_invalid",
                    path=f"$.tools[{index}]",
                )
                actor_names = tuple(
                    _array(
                        tool["actor_names"],
                        1,
                        len(actors),
                        "world_architecture_invalid",
                        path=f"$.tools[{index}].actor_names",
                    )
                )
                if any(
                    not isinstance(actor, str) or actor not in actors for actor in actor_names
                ) or len(set(actor_names)) != len(actor_names):
                    raise DesignError(
                        "world_architecture_invalid",
                        path=f"$.tools[{index}].actor_names",
                        violated_condition="tool actors must be unique declared names",
                        expected_category="array",
                    )
                actor_indexes = tuple(actors.index(actor) + 1 for actor in actor_names)
                tools.append(
                    ToolSurface(
                        index + 1,
                        _text(
                            tool["name"],
                            "world_architecture_invalid",
                            64,
                            path=f"$.tools[{index}].name",
                        ),
                        _text(
                            tool["purpose"],
                            "world_architecture_invalid",
                            300,
                            path=f"$.tools[{index}].purpose",
                        ),
                        actor_indexes,
                        field_array(
                            tool["argument_fields"],
                            0,
                            path=f"$.tools[{index}].argument_fields",
                        ),
                        field_array(
                            tool["result_fields"],
                            1,
                            path=f"$.tools[{index}].result_fields",
                        ),
                    )
                )
            if len({tool.name for tool in tools}) != len(tools):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.tools",
                    violated_condition="tool names must be unique",
                    expected_category="array",
                )
            divergences = tuple(
                EvidenceClaim(
                    _text(
                        obj["statement"],
                        "world_architecture_invalid",
                        500,
                        path=f"$.known_divergences[{index}].statement",
                    ),
                    cast(Any, obj["kind"]),
                    tuple(
                        _array(
                            obj["citation_indexes"],
                            1,
                            6,
                            "world_architecture_invalid",
                            path=f"$.known_divergences[{index}].citation_indexes",
                        )
                    ),
                )
                for index, item in enumerate(
                    _array(
                        raw["known_divergences"],
                        0,
                        16,
                        "world_architecture_invalid",
                        path="$.known_divergences",
                    )
                )
                for obj in (
                    _object(
                        item,
                        {"statement", "kind", "citation_indexes"},
                        "world_architecture_invalid",
                        path=f"$.known_divergences[{index}]",
                    ),
                )
            )
            if any(
                claim.kind not in {"observed", "bounded_inference"}
                or not set(claim.citation_indexes).issubset(citations)
                for claim in divergences
            ):
                raise DesignError(
                    "world_architecture_invalid",
                    path="$.known_divergences",
                    violated_condition="divergences must cite frozen evidence",
                    expected_category="array",
                )
            provisional = WorldArchitecture(
                boundary,
                tuple(entities),
                tuple(tools),
                divergences,
                SemanticCatalog(()),
                ToolCouplingPlan(() if len(tools) == 1 else (tuple(range(1, len(tools) + 1)),)),
                _PENDING,
            )
            return replace(provisional, catalog=SemanticCatalog(_catalog(provisional)))

        field_shape = (
            "Field (exactly these keys, no others):\n"
            "    name      : snake_case [a-z][a-z0-9_]{0,63} (1..64 code points)\n"
            "    category  : one of text|integer|number|boolean|timestamp|identifier|enum|list\n"
            "    required  : boolean\n"
            "    values    : array[1..16] of unique nonempty strings — REQUIRED when category is enum|list, OMITTED otherwise\n"  # noqa: E501
            "    entity_ref: optional snake_case [a-z][a-z0-9_]{0,63} — name of a declared entity"
        )
        shape = (
            f"{field_shape}\n\n"
            "Objective: return one coherent minimal JSON object. Combine related workflow "
            "actions into the fewest coherent tools (1..8). Before returning — and after any "
            "correction — recheck the complete object against every field, cardinality, "
            "uniqueness, reference, actor, and citation rule.\n\n"
            "output (exactly these top-level keys):\n\n"
            "boundary:\n"
            "    name             : stripped text [1..160]\n"
            "    system_of_record : stripped text [1..160]\n"
            "    authority        : stripped text [1..160]\n"
            "    purpose          : stripped text [1..4096 Unicode code points]\n"
            "    actors           : array[1..8] of stripped text [1..80], unique after stripping\n\n"  # noqa: E501
            "entities: array[1..16] of:\n"
            "    name   : stripped text [1..64], unique among entities\n"
            "    purpose: stripped text [1..300]\n"
            "    fields : array[1..24] of Field (unique names; entity_ref must name a declared entity in this object when present)\n\n"  # noqa: E501
            "tools: array[1..8] of:\n"
            "    name            : stripped text [1..64], unique among tools\n"
            "    purpose         : stripped text [1..300]\n"
            "    actor_names     : array[1..N] of exact declared actor names (unique)\n"
            "    argument_fields : array[0..24] of Field (unique names; may be empty)\n"
            "    result_fields   : array[1..24] of Field (unique names)\n\n"
            "known_divergences: array[0..16] of:\n"
            "    statement       : stripped text [1..500]\n"
            "    kind            : \"observed\" or \"bounded_inference\"\n"
            "    citation_indexes: array[1..6] of frozen one-based CitationCatalog indexes\n\n"
            "Example (abbreviated — yours must be complete):\n"
            "{\"boundary\":{\"name\":\"ticket_system\",\"system_of_record\":\"helpdesk_db\","
            "\"authority\":\"support_lead\",\"purpose\":\"Route and resolve support tickets.\","
            "\"actors\":[\"agent\",\"supervisor\"]},"
            "\"entities\":[{\"name\":\"ticket\",\"purpose\":\"A support request.\","
            "\"fields\":[{\"name\":\"status\",\"category\":\"enum\",\"required\":true,"
            "\"values\":[\"open\",\"closed\"]}]}],"
            "\"tools\":[{\"name\":\"assign_ticket\",\"purpose\":\"Assign a ticket to an agent.\","
            "\"actor_names\":[\"agent\"],"
            "\"argument_fields\":[{\"name\":\"ticket_id\",\"category\":\"identifier\",\"required\":true}],"
            "\"result_fields\":[{\"name\":\"assigned_to\",\"category\":\"text\",\"required\":true}]}],"
            "\"known_divergences\":[{\"statement\":\"API may delay updates.\","
            "\"kind\":\"bounded_inference\",\"citation_indexes\":[1]}]}\n\n"
            "Do not return IDs, indexes, digests, Artifact refs, schemas, gates, Judge, or release facts."  # noqa: E501
        )
        value, ref, work = self._direct_commit(
            "world_architecture",
            {
                "need": request.need,
                "claims": json_value(evidence.claims),
                "conflicts": json_value(evidence.conflicts),
                "gaps": evidence.gaps,
                "citation_catalog": json_value(evidence.catalog),
            },
            shape,
            "design.world_architecture",
            compile,
            {"request": (request_ref,), "evidence": (evidence_ref,), "coverage": (evidence_ref,)},
            store,
            graph,
            run_id,
            output_type=WorldArchitecture,
        )
        return replace(value, artifact=ref), ref, work

    def _shared_tool_shards(
        self,
        architecture: WorldArchitecture,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[SharedToolContract, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        contracts: list[SharedToolContract] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        for group in architecture.coupling_plan.groups:

            def compile(
                value: dict[str, Any], members: tuple[int, ...] = group
            ) -> SharedToolContract:
                raw = _object(
                    value,
                    {
                        "atomicity",
                        "concurrency",
                        "idempotency",
                        "ordering",
                        "compensation",
                        "error_policy",
                    },
                    "shared_tool_semantics_invalid",
                )

                name_to_index = {
                    architecture.tools[index - 1].name: index for index in members
                }

                def partition(value: object, name: str) -> tuple[tuple[int, ...], ...]:
                    raw_groups = _array(
                        value,
                        1,
                        len(members),
                        "shared_tool_semantics_invalid",
                        path=f"$.{name}",
                    )
                    resolved: list[tuple[int, ...]] = []
                    for group_number, raw_group in enumerate(raw_groups):
                        entries = _array(
                            raw_group,
                            1,
                            len(members),
                            "shared_tool_semantics_invalid",
                            path=f"$.{name}[{group_number}]",
                        )
                        resolved_members: list[int] = []
                        for entry_number, entry in enumerate(entries):
                            if not isinstance(entry, str) or entry not in name_to_index:
                                raise DesignError(
                                    "shared_tool_semantics_invalid",
                                    path=f"$.{name}[{group_number}][{entry_number}]",
                                    violated_condition=(
                                        "must be a tool NAME listed in input.tool_names; "
                                        f"unknown {entry!r}"
                                    ),
                                    expected_category="string",
                                )
                            resolved_members.append(name_to_index[entry])
                        resolved.append(tuple(resolved_members))
                    result = tuple(resolved)
                    flattened = tuple(index for item in result for index in item)
                    if (
                        any(index not in members for index in flattened)
                        or len(flattened) != len(members)
                        or len(set(flattened)) != len(flattened)
                    ):
                        raise DesignError(
                            "shared_tool_semantics_invalid",
                            path=f"$.{name}",
                            violated_condition=(
                                "use every input tool_names member exactly once; unless evidence "
                                "requires a finer split, one domain containing the complete "
                                "ordered group is valid"
                            ),
                            expected_category="array",
                        )
                    return result

                policy_text = _text(
                    raw["error_policy"],
                    "shared_tool_semantics_invalid",
                    500,
                    path="$.error_policy",
                )
                policy = tuple((member, policy_text) for member in members)
                atomicity = partition(raw["atomicity"], "atomicity")
                concurrency = partition(raw["concurrency"], "concurrency")
                idempotency = partition(raw["idempotency"], "idempotency")
                ordering = tuple(
                    _text(item, "shared_tool_semantics_invalid", 500, path="$.ordering")
                    for item in _array(
                        raw["ordering"], 0, 8, "shared_tool_semantics_invalid", path="$.ordering"
                    )
                )
                compensation = tuple(
                    _text(item, "shared_tool_semantics_invalid", 160, path="$.compensation")
                    for item in _array(
                        raw["compensation"],
                        0,
                        8,
                        "shared_tool_semantics_invalid",
                        path="$.compensation",
                    )
                )
                payload = {
                    "tool_indexes": members,
                    "atomicity": atomicity,
                    "concurrency": concurrency,
                    "idempotency": idempotency,
                    "ordering": ordering,
                    "compensation": compensation,
                    "error_policy": [
                        {"tool_index": index, "policy": text} for index, text in policy
                    ],
                }
                return SharedToolContract(
                    members,
                    atomicity,
                    concurrency,
                    idempotency,
                    ordering,
                    compensation,
                    policy,
                    digest_value(payload),
                    _PENDING,
                )

            projection = {
                "tool_names": [architecture.tools[index - 1].name for index in group],
                "tools": [
                    {
                        "name": architecture.tools[index - 1].name,
                        "purpose": architecture.tools[index - 1].purpose,
                    }
                    for index in group
                ],
                "citations": json_value(evidence.catalog),
            }
            value, ref, work = self._direct_commit(
                "shared_tool_semantics",
                projection,
                "output (exactly these keys, no others):\n\n"
                "atomicity    : array[1..group_size] of sub-arrays of tool NAME strings partitioning input.tool_names exactly once; unless evidence requires a finer split, use one domain containing the complete ordered group\n"  # noqa: E501
                "concurrency  : same partition shape as atomicity\n"
                "idempotency  : same partition shape as atomicity\n"
                "  Example: input tool_names [\"create\",\"close\"] -> [[\"create\",\"close\"]] for each of atomicity/concurrency/idempotency\n"  # noqa: E501
                "ordering     : array[0..8] of STRINGS (not numbers); each stripped nonempty text <=500 code points\n"  # noqa: E501
                "compensation : array[0..8] of STRINGS (not numbers); each stripped nonempty text <=160 code points\n"  # noqa: E501
                "error_policy : one stripped nonempty shared-policy string <=500 code points applying to the complete group\n\n"  # noqa: E501
                "Objective: return compact complete semantics for the frozen group, cover every "
                "member exactly once in each shared dimension, and recheck the whole object after "
                "correction.\n\n"
                "Example (for input tool_names [\"create\",\"close\"]):\n"
                "{\"atomicity\":[[\"create\",\"close\"]],\"concurrency\":[[\"create\",\"close\"]],"
                "\"idempotency\":[[\"create\",\"close\"]],"
                "\"ordering\":[\"create before close\"],\"compensation\":[\"revert creation\"],"
                "\"error_policy\":\"reject invalid requests\"}\n\n"
                "Reference tools by their NAME (from input.tool_names), never by index. "
                "Do not return IDs, digests, Artifact refs, schemas, gates, Judge, or release facts.",  # noqa: E501
                "design.shared_tool_semantics",
                compile,
                {"architecture": (architecture_ref,), "evidence": (evidence_ref,)},
                store,
                graph,
                run_id,
                shard_key="-".join(map(str, group)),
                output_type=SharedToolContract,
            )
            contracts.append(replace(value, artifact=ref))
            refs.append(ref)
            works.append(work)
        return tuple(contracts), tuple(refs), tuple(works)

    def _direct_tools(
        self,
        architecture: WorldArchitecture,
        shared: tuple[SharedToolContract, ...],
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        shared_refs: tuple[ArtifactRef, ...],
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[ToolDraft, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        contracts = {index: contract for contract in shared for index in contract.tool_indexes}
        tools: list[ToolDraft] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        citations = {item.index for item in evidence.catalog.items}
        for surface in architecture.tools:
            selected = contracts.get(surface.tool_index)
            bindings = architecture.catalog.bindings

            def compile(
                value: dict[str, Any],
                tool: ToolSurface = surface,
                shared_contract: SharedToolContract | None = selected,
                frozen_bindings: tuple[SemanticBinding, ...] = bindings,
            ) -> ToolDraft:
                # Resolve field names against THIS tool's bindings only. The global
                # catalog has duplicate field names across tools (every tool has a
                # "status"/"ticket_id"), so resolving against the full catalog would
                # mis-bind a name to another tool's field (last-wins) and produce
                # cross-tool effects that integration cannot satisfy.
                tool_bindings = tuple(
                    b
                    for b in frozen_bindings
                    if len(b.path) > 1 and b.path[1] == str(tool.tool_index)
                )
                raw = _object(
                    value,
                    {
                        "preconditions",
                        "transitions",
                        "postconditions",
                        "errors",
                    },
                    "tool_semantics_invalid",
                )
                tool_lookup = _tool_rule_lookup(tool_bindings, tool)
                pre = _compile_rules(
                    raw["preconditions"],
                    tool_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.preconditions",
                    minimum=1,
                    maximum=6,
                    errors_only=False,
                    effects_min=0,
                    effects_max=0,
                    lookup=tool_lookup,
                    effects_violation=(
                        "preconditions are guard rules; effects must be the empty array [] — "
                        "precondition failure is framework-fixed (reject invoke + preserve "
                        "state); put state-changing behavior in transitions and rejection "
                        "behavior in errors"
                    ),
                )
                _reject_guard_conflicts(pre, "tool_semantics_invalid")
                trans = _compile_rules(
                    raw["transitions"],
                    tool_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.transitions",
                    minimum=1,
                    maximum=6,
                    errors_only=False,
                    lookup=tool_lookup,
                )
                _reject_transition_degeneracy(trans, tool_bindings, tool)
                post = _compile_rules(
                    raw["postconditions"],
                    tool_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.postconditions",
                    minimum=0,
                    maximum=6,
                    errors_only=False,
                    lookup=tool_lookup,
                )
                errors = _compile_rules(
                    raw["errors"],
                    tool_bindings,
                    citations,
                    "tool_semantics_invalid",
                    path="$.errors",
                    minimum=0,
                    maximum=6,
                    errors_only=True,
                    lookup=tool_lookup,
                )
                field_categories = {
                    field.name: (field.category, list(field.values))
                    for field in tool.result_fields
                }
                binding_by_index = {
                    binding.index: binding for binding in tool_bindings
                }
                for _section, rules, base in (
                    ("transitions", trans, "$.transitions"),
                    ("postconditions", post, "$.postconditions"),
                ):
                    for rule_number, rule in enumerate(rules):
                        for effect_number, effect in enumerate(rule.effects):
                            target = binding_by_index.get(
                                effect.target_semantic_index
                            )
                            if target is None:
                                continue
                            category, values = field_categories.get(
                                target.name, ("text", [])
                            )
                            ok, message = _effect_category_ok(category, values, effect)
                            if not ok:
                                raise DesignError(
                                    "tool_semantics_invalid",
                                    path=(
                                        base
                                        + "["
                                        + str(rule_number)
                                        + "].effects["
                                        + str(effect_number)
                                        + "]"
                                    ),
                                    violated_condition=(
                                        "effect value category must match the target "
                                        "field category: " + target.name + " — " + message
                                    ),
                                    expected_category="semantic_draft",
                                )
                if not any(
                    effect.operation not in {"preserve", "reject"}
                    for rule in trans
                    for effect in rule.effects
                ):
                    raise DesignError(
                        "tool_semantics_invalid",
                        path="$.transitions",
                        violated_condition="transitions require a state-changing effect",
                        expected_category="array",
                    )
                digest = _local_rules_digest(
                    tool.tool_index,
                    frozen_bindings,
                    pre,
                    trans,
                    post,
                    errors,
                    shared_contract.digest if shared_contract else None,
                )
                return ToolDraft(
                    tool.tool_index,
                    tool,
                    frozen_bindings,
                    pre,
                    trans,
                    post,
                    errors,
                    shared_contract.digest if shared_contract else None,
                    digest,
                )

            projection = {
                "tool": json_value(surface),
                "fields": _binding_fields_for_llm(bindings, architecture),
                "shared_contract": json_value(selected) if selected else None,
                "citation_catalog": json_value(evidence.catalog),
            }
            value, ref, work = self._direct_commit(
                "tool_semantics",
                projection,
                f"output (exactly these top-level keys):\n\n"
                f"preconditions  : array[1..6] of guard rules (RuleDraft keys: when/effects/"
                f"error_kind/rationale/citation_indexes; error_kind must be null). A guard "
                f"only answers WHEN the tool may be invoked: `when` states the required "
                f"arguments/state, and `effects` MUST be the empty array []. Do NOT write "
                f"preserve/reject effects here: when a precondition is not satisfied the "
                f"framework itself rejects the invoke and preserves state — no per-rule "
                f"effect models that, and a precondition carrying any effect is rejected "
                f"as tool_semantics_invalid. Put all state-changing behavior in "
                f"transitions and rejection behavior in errors. Write guards in POSITIVE "
                f"form: `when` holds the condition that MUST hold for the call to proceed. "
                f"Example: a required argument guest_id is written as "
                f"`when: [guest_id exists]` — do NOT write `not_exists` for a required "
                f"input (that inverts the guard and fails integration). Guards are AND-ed and must hold together: do NOT split alternatives into multiple eq guards on the same field (rejected at compile); express alternatives as transitions.\n\n"  # noqa: E501
                f"transitions    : array[1..6] of {_RULE_DRAFT_SHAPE} (non-error; at least one effect must be state-changing — i.e. not preserve or reject). Two transitions with IDENTICAL when conditions are rejected (they would fire together and the last one would silently win): merge them into one rule or differentiate the conditions. A when may reference argument fields or state fields by name — but a state field referenced in a when MUST be changed by some transition (otherwise the condition can never vary; write an empty when for unconditional defaults). Effects may only change state (result) fields, never arguments.\n\n"  # noqa: E501
                f"postconditions : array[0..6] of {_RULE_DRAFT_SHAPE} (non-error)\n\n"
                f"errors         : array[0..6] of {_RULE_DRAFT_SHAPE} (errors-only: error_kind must be a snake_case string)\n\n"  # noqa: E501
                "Reference fields by their NAME (from input.fields), not by index.\n\n"
                "Objective: return compact complete semantics for the frozen tool and recheck "
                "every section after correction.\n\n"
                "Do not return tool indexes, shared contracts, IDs, digests, schemas, gates, "
                "Judge, or release facts.",  # noqa: E501
                "design.tool_semantics",
                compile,
                {
                    "architecture": (architecture_ref,),
                    "shared_tools": shared_refs,
                    "evidence": (evidence_ref,),
                },
                store,
                graph,
                run_id,
                shard_key=surface.name,
                output_type=ToolDraft,
            )
            tools.append(value)
            refs.append(ref)
            works.append(work)
        return tuple(tools), tuple(refs), tuple(works)

    def _direct_rules(
        self,
        architecture: WorldArchitecture,
        tools: tuple[ToolDraft, ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        tool_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorldRuleSet, ArtifactRef, ArtifactRef]:
        def compile(value: dict[str, Any]) -> WorldRuleSet:
            raw = _object(value, {"initial_rules", "invariants"}, "world_rules_invalid")
            initial = _compile_rules(
                raw["initial_rules"],
                architecture.catalog.bindings,
                set(),
                "world_rules_invalid",
                path="$.initial_rules",
                minimum=0,
                maximum=8,
                errors_only=False,
            )
            invariants = _compile_rules(
                raw["invariants"],
                architecture.catalog.bindings,
                set(),
                "world_rules_invalid",
                path="$.invariants",
                minimum=0,
                maximum=16,
                errors_only=False,
            )
            local = {
                json.dumps(json_value(rule), sort_keys=True)
                for tool in tools
                for section in (
                    tool.preconditions,
                    tool.transitions,
                    tool.postconditions,
                    tool.errors,
                )
                for rule in section
            }
            if any(
                json.dumps(json_value(rule), sort_keys=True) in local
                for rule in (*initial, *invariants)
            ):
                raise DesignError(
                    "world_rules_duplicate_local_rule",
                    path="$",
                    violated_condition="world rules may not duplicate local tool rules",
                    expected_category="semantic_draft",
                )
            return WorldRuleSet(
                initial,
                invariants,
                digest_value({"initial_rules": initial, "invariants": invariants}),
                _PENDING,
            )

        arch_for_llm = json_value(architecture)
        arch_for_llm.pop("catalog", None)
        arch_for_llm["fields"] = _binding_fields_for_llm(
            architecture.catalog.bindings, architecture
        )
        value, ref, work = self._direct_commit(
            "world_rules",
            {
                "architecture": arch_for_llm,
                "tools": _tools_rules_for_llm(tools),
            },
            "output (exactly these top-level keys):\n\n"
            f"initial_rules : array[0..8] of {_RULE_DRAFT_SHAPE} (non-error; citation_indexes MUST be [] — no CitationCatalog is supplied to this node)\n\n"  # noqa: E501
            f"invariants    : array[0..16] of {_RULE_DRAFT_SHAPE} (non-error; citation_indexes MUST be [] — no CitationCatalog is supplied to this node)\n\n"  # noqa: E501
            "Reference fields by their NAME (from input.architecture.fields), not by index.\n\n"
            "Objective: return only necessary initial and cross-tool rules not duplicated by "
            "local tool rules; empty arrays are valid. Recheck the complete object after "
            "correction.\n\n"
            "Do not return IDs, digests, schemas, gates, Judge, or release facts.",  # noqa: E501
            "design.world_rules",
            compile,
            {"architecture": (architecture_ref,), "tool_semantics": tool_refs},
            store,
            graph,
            run_id,
            output_type=WorldRuleSet,
        )
        return replace(value, artifact=ref), ref, work

    def _direct_curriculum(
        self,
        architecture: WorldArchitecture,
        rules: WorldRuleSet,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        rules_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[CurriculumPlan, ArtifactRef, ArtifactRef]:
        citations = {item.index for item in evidence.catalog.items}

        def compile(value: dict[str, Any]) -> CurriculumPlan:
            raw = _object(value, {"families"}, "curriculum_plan_invalid")
            families: list[CurriculumFamily] = []
            for index, item in enumerate(
                _array(raw["families"], 1, 8, "curriculum_plan_invalid", path="$.families")
            ):
                actor_lookup = {
                    name: position
                    for position, name in enumerate(architecture.boundary.actors, start=1)
                }
                tool_lookup = {tool.name: tool.tool_index for tool in architecture.tools}
                family = _object(
                    item,
                    {
                        "task_family_id",
                        "objective",
                        "actor",
                        "tools",
                        "dimensions",
                        "sampling_intent",
                        "citation_indexes",
                    },
                    "curriculum_plan_invalid",
                    path=f"$.families[{index}]",
                )
                task_id = _text(
                    family["task_family_id"],
                    "curriculum_plan_invalid",
                    64,
                    path=f"$.families[{index}].task_family_id",
                )
                if not _NAME.fullmatch(task_id):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].task_family_id",
                        violated_condition="task family id must use the declared grammar",
                        expected_category="string",
                    )
                actor_name = family["actor"]
                if not isinstance(actor_name, str) or actor_name not in actor_lookup:
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].actor",
                        violated_condition=(
                            f"actor must name a declared boundary actor; unknown {actor_name!r}"
                        ),
                        expected_category="string",
                    )
                actor_index = actor_lookup[actor_name]
                raw_tools = _array(
                    family["tools"],
                    1,
                    len(architecture.tools),
                    "curriculum_plan_invalid",
                    path=f"$.families[{index}].tools",
                )
                resolved_tools: list[int] = []
                for tool_position, raw_tool in enumerate(raw_tools):
                    if not isinstance(raw_tool, str) or raw_tool not in tool_lookup:
                        raise DesignError(
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].tools[{tool_position}]",
                            violated_condition=(
                                f"tool must name a declared tool; unknown {raw_tool!r}"
                            ),
                            expected_category="string",
                        )
                    resolved_tools.append(tool_lookup[raw_tool])
                tool_indexes = tuple(resolved_tools)
                if len(set(tool_indexes)) != len(tool_indexes):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].tools",
                        violated_condition="family tools must be unique",
                        expected_category="array",
                    )
                cited = tuple(
                    _array(
                        family["citation_indexes"],
                        1,
                        6,
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].citation_indexes",
                    )
                )
                if any(
                    type(citation) is not int or citation not in citations for citation in cited
                ) or len(set(cited)) != len(cited):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].citation_indexes",
                        violated_condition="family citations must be unique frozen indexes",
                        expected_category="array",
                    )
                dimensions: list[DifficultyDimension] = []
                for dimension_index, dimension in enumerate(
                    _array(
                        family["dimensions"],
                        1,
                        6,
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                    )
                ):
                    raw_dimension = _object(
                        dimension,
                        {"name", "meaning", "levels"},
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions[{dimension_index}]",
                    )
                    levels: list[DifficultyLevel] = []
                    for level_index, level in enumerate(
                        _array(
                            raw_dimension["levels"],
                            2,
                            5,
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}].levels",
                        )
                    ):
                        raw_level = _object(
                            level,
                            {"name", "meaning"},
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}]",
                        )
                        try:
                            levels.append(
                                DifficultyLevel(
                                    _text(
                                        raw_level["name"],
                                        "curriculum_plan_invalid",
                                        40,
                                        path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}].name",
                                    ),
                                    _text(
                                        raw_level["meaning"],
                                        "curriculum_plan_invalid",
                                        300,
                                        path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}].meaning",
                                    ),
                                )
                            )
                        except ValueError as exc:
                            raise DesignError(
                                "curriculum_plan_invalid",
                                path=f"$.families[{index}].dimensions[{dimension_index}].levels[{level_index}]",
                                violated_condition="difficulty level must use the declared grammar",
                                expected_category="object",
                            ) from exc
                    try:
                        dimensions.append(
                            DifficultyDimension(
                                _text(
                                    raw_dimension["name"],
                                    "curriculum_plan_invalid",
                                    40,
                                    path=f"$.families[{index}].dimensions[{dimension_index}].name",
                                ),
                                _text(
                                    raw_dimension["meaning"],
                                    "curriculum_plan_invalid",
                                    300,
                                    path=f"$.families[{index}].dimensions[{dimension_index}].meaning",
                                ),
                                tuple(levels),
                            )
                        )
                    except ValueError as exc:
                        raise DesignError(
                            "curriculum_plan_invalid",
                            path=f"$.families[{index}].dimensions[{dimension_index}]",
                            violated_condition="difficulty dimension must use the declared grammar",
                            expected_category="object",
                        ) from exc
                compiled_dimensions = tuple(dimensions)
                if len({dimension.name for dimension in compiled_dimensions}) != len(
                    compiled_dimensions
                ):
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                        violated_condition="dimension names must be unique",
                        expected_category="array",
                    )
                try:
                    schema = compile_difficulty_schema(task_id, compiled_dimensions)
                except ValueError as exc:
                    raise DesignError(
                        "curriculum_plan_invalid",
                        path=f"$.families[{index}].dimensions",
                        violated_condition=(
                            "difficulty schema must use declared dimensions and levels"
                        ),
                        expected_category="array",
                    ) from exc
                families.append(
                    CurriculumFamily(
                        index + 1,
                        task_id,
                        _text(
                            family["objective"],
                            "curriculum_plan_invalid",
                            500,
                            path=f"$.families[{index}].objective",
                        ),
                        actor_index,
                        tool_indexes,
                        schema,
                        _text(
                            family["sampling_intent"],
                            "curriculum_plan_invalid",
                            300,
                            path=f"$.families[{index}].sampling_intent",
                        ),
                        cited,
                    )
                )
            if len({family.task_family_id for family in families}) != len(families):
                raise DesignError(
                    "curriculum_plan_invalid",
                    path="$.families",
                    violated_condition="family ids must be unique",
                    expected_category="array",
                )
            return CurriculumPlan(tuple(families), _PENDING)

        value, ref, work = self._direct_commit(
            "curriculum_plan",
            {
                "architecture": json_value(architecture),
                "world_rules": json_value(rules),
                "citation_catalog": json_value(evidence.catalog),
            },
            "output (exactly one top-level key \"families\"):\n\n"
            "families: array[1..8] of:\n"
            "    task_family_id  : snake_case [a-z][a-z0-9_]{0,63} (1..64 code points)\n"
            "    objective       : stripped nonempty text <=500 code points\n"
            "    actor           : string — a declared actor NAME from input.architecture.boundary.actors (NOT an index)\n"  # noqa: E501
            "    tools           : array[1..tool_count] of unique declared tool NAMEs from input.architecture.tools (NOT indexes)\n"  # noqa: E501
            "    dimensions      : array[1..6] of (unique names):\n"
            "        name   : [a-z][a-z0-9_-]{0,39} (1..40 code points)\n"
            "        meaning: stripped nonempty text <=300 code points\n"
            "        levels  : array[2..5] of:\n"
            "            name   : [a-z][a-z0-9_-]{0,39} (1..40 code points)\n"
            "            meaning: stripped nonempty text <=300 code points\n"
            "    sampling_intent : stripped nonempty text <=300 code points\n"
            "    citation_indexes: array[1..6] of unique frozen one-based CitationCatalog indexes\n\n"  # noqa: E501
            "Example (abbreviated — yours must be complete):\n"
            "{\"families\":[{\"task_family_id\":\"resolve_ticket\","
            "\"objective\":\"Resolve a support ticket.\","
            "\"actor\":\"agent\",\"tools\":[\"assign_ticket\"],"
            "\"dimensions\":[{\"name\":\"urgency\",\"meaning\":\"How urgent the ticket is.\","
            "\"levels\":[{\"name\":\"low\",\"meaning\":\"Low urgency.\"},"
            "{\"name\":\"high\",\"meaning\":\"High urgency.\"}]}],"
            "\"sampling_intent\":\"favor high urgency.\",\"citation_indexes\":[1]}]}\n\n"
            "Reference actors and tools by their NAME (from input.architecture), never by index. "
            "Objective: define compact parameterized task families using the frozen catalog; "
            "retain the accepted hyphenated dimension and level names without normalization, "
            "and recheck the complete object after correction.\n\n"
            "Do not return family indexes, difficulty schema keys, digests, IDs, seeds, "
            "rewards, verifier cases, gates, Judge, or release facts.",  # noqa: E501
            "design.curriculum_plan",
            compile,
            {
                "architecture": (architecture_ref,),
                "rules": (rules_ref,),
                "evidence": (evidence_ref,),
            },
            store,
            graph,
            run_id,
            output_type=CurriculumPlan,
        )
        return replace(value, artifact=ref), ref, work

    def _direct_tasks(
        self,
        architecture: WorldArchitecture,
        tools: tuple[ToolDraft, ...],
        rules: WorldRuleSet,
        curriculum: CurriculumPlan,
        evidence: EvidenceGraph,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        architecture_ref: ArtifactRef,
        tool_refs: tuple[ArtifactRef, ...],
        curriculum_ref: ArtifactRef,
        rules_ref: ArtifactRef,
        evidence_ref: ArtifactRef,
    ) -> tuple[tuple[TaskRequirement, ...], tuple[ArtifactRef, ...], tuple[ArtifactRef, ...]]:
        citations = {item.index for item in evidence.catalog.items}
        result: list[TaskRequirement] = []
        refs: list[ArtifactRef] = []
        works: list[ArtifactRef] = []
        for family in curriculum.families:

            def compile(
                value: dict[str, Any], frozen: CurriculumFamily = family
            ) -> TaskRequirement:
                raw = _object(
                    value,
                    {
                        "public_goal_fields",
                        "initial_rules",
                        "success_rules",
                        "failure_rules",
                        "terminal_rules",
                    },
                    "task_requirement_invalid",
                )
                goal_lookup = _goal_name_lookup(architecture)
                tool_names = {tool.tool_index: tool.name for tool in architecture.tools}
                bare_declarers: dict[str, list[str]] = {}
                for binding in architecture.catalog.bindings:
                    if binding.name not in bare_declarers:
                        bare_declarers[binding.name] = []
                    declarer = tool_names[int(binding.path[1])]
                    if declarer not in bare_declarers[binding.name]:
                        bare_declarers[binding.name].append(declarer)
                raw_goal_fields = _array(
                    raw["public_goal_fields"],
                    1,
                    12,
                    "task_requirement_invalid",
                    path="$.public_goal_fields",
                )
                resolved_fields: list[int] = []
                for goal_number, raw_field in enumerate(raw_goal_fields):
                    if not isinstance(raw_field, str) or raw_field not in goal_lookup:
                        ambiguity_note = None
                        if (
                            isinstance(raw_field, str)
                            and len(bare_declarers.get(raw_field, [])) > 1
                        ):
                            ambiguity_note = (
                                "the bare name is declared on "
                                + " and ".join(bare_declarers[raw_field])
                                + "; write tool.field"
                            )
                        raise DesignError(
                            "task_requirement_invalid",
                            path=f"$.public_goal_fields[{goal_number}]",
                            violated_condition=_goal_field_correction(
                                raw_field, goal_lookup, ambiguity_note
                            ),
                            expected_category="string",
                        )
                    resolved_fields.append(goal_lookup[raw_field])
                fields = tuple(resolved_fields)
                if len(set(fields)) != len(fields):
                    raise DesignError(
                        "task_requirement_invalid",
                        path="$.public_goal_fields",
                        violated_condition="public goal fields must be unique",
                        expected_category="array",
                    )
                tool_name_by_index = {
                    tool.tool_index: tool.name for tool in architecture.tools
                }

                def _section_lookup(sources: set[str]) -> dict[str, int]:
                    lookup: dict[str, int] = {}
                    seen_bare: dict[str, int] = {}
                    for binding in architecture.catalog.bindings:
                        if binding.source not in sources:
                            continue
                        tool_name = tool_name_by_index[int(binding.path[1])]
                        lookup[f"{tool_name}.{binding.name}"] = binding.index
                        if binding.name in seen_bare:
                            seen_bare[binding.name] = -1
                        else:
                            seen_bare[binding.name] = binding.index
                    for name, index in seen_bare.items():
                        if index != -1:
                            lookup[name] = index
                    return lookup

                initial_lookup = _section_lookup({"argument", "reset_state"})
                outcome_lookup = _section_lookup({"argument", "post_state"})
                outcome_effects_violation = (
                    "success/failure/terminal rules are when-only patterns; effects must be "
                    "the empty array [] — the framework derives reward and termination from "
                    "the matching when conditions"
                )
                initial_rules = _compile_task_rules(
                    raw["initial_rules"],
                    architecture.catalog.bindings,
                    citations,
                    path="$.initial_rules",
                    minimum=0,
                    maximum=8,
                    lookup=initial_lookup,
                )
                success_rules = _compile_task_rules(
                    raw["success_rules"],
                    architecture.catalog.bindings,
                    citations,
                    path="$.success_rules",
                    minimum=1,
                    maximum=8,
                    effects_min=0,
                    effects_max=0,
                    effects_violation=outcome_effects_violation,
                    lookup=outcome_lookup,
                )
                failure_rules = _compile_task_rules(
                    raw["failure_rules"],
                    architecture.catalog.bindings,
                    citations,
                    path="$.failure_rules",
                    minimum=0,
                    maximum=8,
                    effects_min=0,
                    effects_max=0,
                    effects_violation=outcome_effects_violation,
                    lookup=outcome_lookup,
                )
                terminal_rules = _compile_task_rules(
                    raw["terminal_rules"],
                    architecture.catalog.bindings,
                    citations,
                    path="$.terminal_rules",
                    minimum=1,
                    maximum=8,
                    effects_min=0,
                    effects_max=0,
                    effects_violation=outcome_effects_violation,
                    lookup=outcome_lookup,
                )
                reset_violation = _verify_initial_rules(
                    initial_rules, _reset_value_map(architecture)
                )
                if reset_violation is not None:
                    raise DesignError(
                        "task_requirement_invalid",
                        path="$.initial_rules",
                        violated_condition=reset_violation,
                        expected_category="semantic_draft",
                    )
                outcome_violation = _verify_family_outcome(
                    frozen.tool_indexes, tools, architecture, success_rules, failure_rules
                )
                if outcome_violation is not None:
                    raise DesignError(
                        "task_requirement_invalid",
                        path="$",
                        violated_condition=outcome_violation,
                        expected_category="semantic_draft",
                    )
                return TaskRequirement(
                    frozen.task_family_index,
                    fields,
                    initial_rules,
                    success_rules,
                    failure_rules,
                    terminal_rules,
                    _PENDING,
                )

            projection = {
                "family": {
                    "objective": family.objective,
                    "actor": architecture.boundary.actors[family.actor_index - 1],
                    "tools": [
                        architecture.tools[index - 1].name for index in family.tool_indexes
                    ],
                    "difficulty_schema": {
                        "dimensions": json_value(family.difficulty_schema.dimensions),
                    },
                    "sampling_intent": family.sampling_intent,
                    "citation_indexes": list(family.citation_indexes),
                },
                "semantic_catalog": {
                    "fields": _task_semantic_fields(architecture),
                },
                "world_rules": {
                    "initial_rules": _rules_for_llm(
                        rules.initial_rules, architecture.catalog.bindings
                    ),
                    "invariants": _rules_for_llm(
                        rules.invariants, architecture.catalog.bindings
                    ),
                },
                "tools": _tools_rules_for_llm(tools, family.tool_indexes),
                "citation_catalog": json_value(evidence.catalog),
                "reachability_policy": {"action_tool_indexes": family.tool_indexes},
            }
            value, ref, work = self._direct_commit(
                "task_requirement",
                projection,
                "output (exactly these top-level keys):\n\n"
                f"RuleDraft keys for every section ({_TASK_RULE_DRAFT_SHAPE}); "
                "success/failure/terminal are when-only patterns (effects MUST be []); "
                "initial_rules carry set effects that state reset values.\n\n"
                "public_goal_fields : array[1..12] of unique field NAME strings from input.semantic_catalog.fields\n\n"  # noqa: E501
                "initial_rules      : array[0..8] of reset-state rules: when MUST be [] and every effect MUST set the field to the exact reset_value disclosed in the matching reset_state row of input.semantic_catalog.fields (copy those values verbatim). The framework verifies each rule deterministically against the fresh reset state and rejects any mismatch.\n\n"  # noqa: E501
                "success_rules      : array[1..8] of WHEN-ONLY patterns (effects MUST be []): conditions on arguments and post-state fields (use source post_state rows) that mark task success. MANDATORY: at least one.\n\n"  # noqa: E501
                "failure_rules      : array[0..8] of WHEN-ONLY patterns (effects MUST be []): the FAILURE condition written in positive form (e.g. status eq failed), NOT a rejection-path double negative. Do NOT write reject/preserve effects.\n\n"  # noqa: E501
                "terminal_rules     : array[1..8] of WHEN-ONLY patterns (effects MUST be []): conditions that end the episode even without success/failure. MANDATORY: at least one.\n\n"  # noqa: E501
                "Reference fields by their NAME (from input.semantic_catalog.fields), not by index. When several tools share a field name, write tool_name.field (e.g. submit_reservation.status); initial_rules use reset_state rows, success/failure/terminal use post_state rows.\n\n"  # noqa: E501
                "DETERMINISTIC OUTCOME GATE: the framework simulates the frozen tool transitions for this family's action sequence (primary difficulty, guard-satisfying arguments, starting from the disclosed reset values) and REQUIRES at least one success pattern to hold afterwards and no failure pattern — a task whose success is unreachable in this simulation is rejected with the simulated post-state in the correction. Align your success/failure rules with what the tool transitions can actually reach.\n\n"  # noqa: E501
                "Objective: return compact complete reset, success, failure, and terminal "
                "semantics for the frozen task family; its DifficultySchema is read-only. "
                "Recheck every section after correction.\n\n"
                "Do not return task-family indexes, IDs, digests, schemas, rewards, gates, "
                "Judge, or release facts.",  # noqa: E501
                "design.task_requirement",
                compile,
                {
                    "architecture": (architecture_ref,),
                    "tool_semantics": tuple(tool_refs[index - 1] for index in family.tool_indexes),
                    "curriculum": (curriculum_ref,),
                    "rules": (rules_ref,),
                    "evidence": (evidence_ref,),
                },
                store,
                graph,
                run_id,
                shard_key=family.task_family_id,
                output_type=TaskRequirement,
            )
            result.append(replace(value, artifact=ref))
            refs.append(ref)
            works.append(work)
        return tuple(result), tuple(refs), tuple(works)

    def _modeling_gate(
        self,
        evidence: EvidenceGraph,
        architecture: WorldArchitecture,
        shared: tuple[SharedToolContract, ...],
        tools: tuple[ToolDraft, ...],
        rules: WorldRuleSet,
        curriculum: CurriculumPlan,
        requirements: tuple[TaskRequirement, ...],
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        evidence_ref: ArtifactRef,
        architecture_ref: ArtifactRef,
        shared_refs: tuple[ArtifactRef, ...],
        tool_refs: tuple[ArtifactRef, ...],
        rules_ref: ArtifactRef,
        curriculum_ref: ArtifactRef,
        task_refs: tuple[ArtifactRef, ...],
    ) -> tuple[DesignContract, ArtifactRef, ArtifactRef]:
        if tuple(task.task_family_index for task in requirements) != tuple(
            family.task_family_index for family in curriculum.families
        ):
            raise DesignError("modeling_gate_task_closure_invalid", correctable=False)
        recipes: list[AssuranceRecipe] = []
        for family, task in zip(curriculum.families, requirements, strict=True):
            primary = tuple(
                (dimension.name, dimension.levels[0].name)
                for dimension in family.difficulty_schema.dimensions
            )
            alternate = tuple(
                (
                    dimension.name,
                    (dimension.levels[1].name if index == 0 else dimension.levels[0].name),
                )
                for index, dimension in enumerate(family.difficulty_schema.dimensions)
            )
            task_digest = digest_value(
                {"task_requirement": json_value(task), "family": json_value(family)}
            )
            for tool_index in family.tool_indexes:
                tool = tools[tool_index - 1]
                payload = {
                    "task_family_index": family.task_family_index,
                    "tool_index": tool_index,
                    "task_digest": task_digest,
                    "difficulty_digest": family.difficulty_schema.schema_digest,
                    "tool_digest": tool.local_rules_digest,
                    "actor": architecture.boundary.actors[family.actor_index - 1],
                    "primary_difficulty": primary,
                    "alternate_difficulty": alternate,
                    "action_tool_indexes": family.tool_indexes,
                }
                recipe_digest = digest_value(payload)
                recipes.append(
                    AssuranceRecipe(
                        task_family_index=family.task_family_index,
                        tool_index=tool_index,
                        task_digest=task_digest,
                        difficulty_digest=family.difficulty_schema.schema_digest,
                        tool_digest=tool.local_rules_digest,
                        actor=architecture.boundary.actors[family.actor_index - 1],
                        primary_difficulty=primary,
                        alternate_difficulty=alternate,
                        action_tool_indexes=family.tool_indexes,
                        recipe_digest=recipe_digest,
                    )
                )
        executable: list[ExecutableTaskContract] = []
        categories = _catalog_categories(architecture)
        for family, task in zip(curriculum.families, requirements, strict=True):
            public = tuple(
                (f"/goal/{index}", categories[index - 1]) for index in task.public_goal_fields
            )
            initial = tuple(
                (f"/tools/{tool.tool_index}/{field.name}", field.category)
                for tool in architecture.tools
                for field in (*tool.argument_fields, *tool.result_fields)
            )
            bindings = tuple(EvaluatorGoalBinding(path, path) for path, _ in public)
            reward = RewardSpec()
            termination = TerminationSpec()
            required = tuple(
                recipe.recipe_digest
                for recipe in recipes
                if recipe.task_family_index == family.task_family_index
            )
            verification = VerificationRequirements(family.task_family_index, True, required)
            executable.append(
                ExecutableTaskContract(
                    family.task_family_index,
                    task,
                    public,
                    initial,
                    bindings,
                    digest_value({"objective": family.objective, "public_goal_schema": public}),
                    reward,
                    digest_value(reward),
                    termination,
                    digest_value(termination),
                    verification,
                    digest_value(verification),
                )
            )

        def compile(value: dict[str, Any]) -> DesignContract:
            if value != {"closed": True}:
                raise DesignError("modeling_gate_invalid", correctable=False)
            return DesignContract(
                evidence,
                architecture,
                shared,
                tools,
                rules,
                curriculum,
                requirements,
                tuple(executable),
                tuple(recipes),
                _PENDING,
            )

        payload = {"closed": True}
        node = graph.execute(
            store,
            run_id,
            "modeling_gate",
            {
                "evidence": (evidence_ref,),
                "architecture": (architecture_ref,),
                "shared_tools": shared_refs,
                "tool_semantics": tool_refs,
                "curriculum": (curriculum_ref,),
                "tasks": task_refs,
                "rules": (rules_ref,),
            },
            "design.environment_design",
            lambda _: payload,
            compile,
            {
                "evidence": evidence_ref.digest,
                "architecture": architecture_ref.digest,
                "shared_tools": [ref.digest for ref in shared_refs],
                "tool_semantics": [ref.digest for ref in tool_refs],
                "rules": rules_ref.digest,
                "curriculum": curriculum_ref.digest,
                "tasks": [ref.digest for ref in task_refs],
                "output_shape": "EnvironmentDesign@1",
            },
            artifact_projection=_design_artifact_value,
            output_type=DesignContract,
        )
        return (
            replace(node.value, artifact=node.artifact, work_refs=(node.work,)),
            node.artifact,
            node.work,
        )

    def run(
        self,
        request: EnvironmentRequest,
        store: ArtifactStore,
        graph: GraphRunner,
        run_id: str,
        *,
        resume: ResumeContext | None = None,
    ) -> DesignResult:
        request_ref = store.put_json("control.design_request", {"need_digest": request.need_digest})
        plan, plan_ref, plan_work = self._research_plan(request, store, graph, run_id, request_ref)
        sources, acquire_ref, acquire_work = self._research_acquire(
            plan, store, graph, run_id, plan_ref
        )
        evidence, evidence_ref, synthesis_work = self._research_synthesis(
            request, plan, sources, store, graph, run_id, request_ref, plan_ref, acquire_ref
        )
        architecture, architecture_ref, architecture_work = self._direct_architecture(
            request, evidence, store, graph, run_id, request_ref, evidence_ref
        )
        shared, shared_refs, shared_works = self._shared_tool_shards(
            architecture, evidence, store, graph, run_id, architecture_ref, evidence_ref
        )
        tools, tool_refs, tool_works = self._direct_tools(
            architecture,
            shared,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            shared_refs,
            evidence_ref,
        )
        rules, rules_ref, rules_work = self._direct_rules(
            architecture, tools, store, graph, run_id, architecture_ref, tool_refs
        )
        curriculum, curriculum_ref, curriculum_work = self._direct_curriculum(
            architecture,
            rules,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            rules_ref,
            evidence_ref,
        )
        tasks, task_refs, task_works = self._direct_tasks(
            architecture,
            tools,
            rules,
            curriculum,
            evidence,
            store,
            graph,
            run_id,
            architecture_ref,
            tool_refs,
            curriculum_ref,
            rules_ref,
            evidence_ref,
        )
        design, design_ref, gate_work = self._modeling_gate(
            evidence,
            architecture,
            shared,
            tools,
            rules,
            curriculum,
            tasks,
            store,
            graph,
            run_id,
            evidence_ref,
            architecture_ref,
            shared_refs,
            tool_refs,
            rules_ref,
            curriculum_ref,
            task_refs,
        )
        works = (
            plan_work,
            acquire_work,
            synthesis_work,
            architecture_work,
            *shared_works,
            *tool_works,
            rules_work,
            curriculum_work,
            *task_works,
            gate_work,
        )
        refs = (
            request_ref,
            plan_ref,
            acquire_ref,
            evidence_ref,
            architecture_ref,
            *shared_refs,
            *tool_refs,
            rules_ref,
            curriculum_ref,
            *task_refs,
            design_ref,
        )
        return DesignResult(replace(design, work_refs=works), works, refs)

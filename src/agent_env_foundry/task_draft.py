"""Public TaskDraft contracts and Host-owned answer materialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Self, cast

from agent_env_foundry.environment import (
    JSONObject,
    JSONValue,
    ToolSpec,
    validate_tool_catalog,
)
from agent_env_foundry.errors import EnvironmentRuntimeError
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import _hex_digest, canonical_bytes, sha256_hex
from agent_env_foundry.schema import SchemaError, validate_schema_document
from agent_env_foundry.task_goal import TraceEvent

SAMPLING_TARGET_FORMAT = "sampling-target/1"
TASK_DRAFT_FORMAT = "task-draft/1"
GoalShape = Literal["atom", "all", "if", "foreach"]
OutcomeClass = Literal["query", "transition", "refusal"]
ScalarOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte"]
_SHAPES = frozenset({"atom", "all", "if", "foreach"})
_OUTCOMES = frozenset({"query", "transition", "refusal"})
_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})


@dataclass(frozen=True, slots=True)
class SamplingTarget:
    required_goal_shape: GoalShape
    required_focus_tools: tuple[str, ...]
    required_outcome: OutcomeClass
    prior_structure_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.required_goal_shape not in _SHAPES:
            raise ValueError("SamplingTarget has an unsupported Goal shape")
        if self.required_outcome not in _OUTCOMES:
            raise ValueError("SamplingTarget has an unsupported outcome")
        _unique_texts(self.required_focus_tools, "required_focus_tools", empty=False)
        _unique_texts(self.prior_structure_ids, "prior_structure_ids", empty=True)
        for value in self.prior_structure_ids:
            _digest(value, "prior structure ID")

    @property
    def target_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": SAMPLING_TARGET_FORMAT,
            "required_goal_shape": self.required_goal_shape,
            "required_focus_tools": list(self.required_focus_tools),
            "required_outcome": self.required_outcome,
            "prior_structure_ids": list(self.prior_structure_ids),
        }


@dataclass(frozen=True, slots=True)
class PublicValueRef:
    kind: Literal["task_literal", "reset", "observation"]
    pointer: str | None = None
    step: int | None = None
    value: JSONValue = None

    def __post_init__(self) -> None:
        if self.kind == "task_literal":
            if self.pointer is not None or self.step is not None or not is_json_value(self.value):
                raise ValueError("task literal requires only one JSON value")
        elif self.kind == "reset":
            _pointer(self.pointer, "reset pointer")
            if self.step is not None or self.value is not None:
                raise ValueError("reset value requires only a pointer")
        elif self.kind == "observation":
            _pointer(self.pointer, "observation pointer")
            _positive(self.step, "observation step")
            if self.value is not None:
                raise ValueError("observation value cannot contain a literal")
        else:
            raise ValueError("unsupported public value source")
        object.__setattr__(self, "value", _copy_json(self.value))

    @classmethod
    def task_literal(cls, value: JSONValue) -> Self:
        return cls("task_literal", value=value)

    @classmethod
    def reset(cls, pointer: str) -> Self:
        return cls("reset", pointer=pointer)

    @classmethod
    def observation(cls, step: int, pointer: str) -> Self:
        return cls("observation", pointer=pointer, step=step)

    def to_document(self) -> JSONObject:
        if self.kind == "task_literal":
            return {"kind": self.kind, "value": _copy_json(self.value)}
        if self.kind == "reset":
            return {"kind": self.kind, "pointer": cast(str, self.pointer)}
        return {
            "kind": self.kind,
            "step": cast(int, self.step),
            "pointer": cast(str, self.pointer),
        }


@dataclass(frozen=True, slots=True)
class AnswerProjection:
    kind: Literal["source", "object", "array"]
    source: PublicValueRef | None = None
    fields: tuple[tuple[str, AnswerProjection], ...] = ()
    items: tuple[AnswerProjection, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "source":
            if not isinstance(self.source, PublicValueRef) or self.fields or self.items:
                raise ValueError("source projection requires only a PublicValueRef")
        elif self.kind == "object":
            names = [name for name, _ in self.fields]
            if self.source is not None or self.items or len(names) != len(set(names)):
                raise ValueError("object projection has invalid fields")
            if any(
                not name or not isinstance(value, AnswerProjection) for name, value in self.fields
            ):
                raise ValueError("object projection fields must be named projections")
            object.__setattr__(self, "fields", tuple(sorted(self.fields)))
        elif self.kind == "array":
            if self.source is not None or self.fields or not self.items:
                raise ValueError("array projection requires one or more items")
            if any(not isinstance(value, AnswerProjection) for value in self.items):
                raise ValueError("array projection items must be projections")
        else:
            raise ValueError("unsupported AnswerProjection kind")

    @classmethod
    def from_source(cls, source: PublicValueRef) -> Self:
        return cls("source", source=source)

    @classmethod
    def from_object(cls, fields: dict[str, AnswerProjection]) -> Self:
        return cls("object", fields=tuple(fields.items()))

    @classmethod
    def from_array(cls, items: tuple[AnswerProjection, ...]) -> Self:
        return cls("array", items=items)

    def to_document(self) -> JSONObject:
        if self.kind == "source":
            return {"kind": self.kind, "source": cast(PublicValueRef, self.source).to_document()}
        if self.kind == "object":
            return {
                "kind": self.kind,
                "fields": {name: value.to_document() for name, value in self.fields},
            }
        return {"kind": self.kind, "items": [value.to_document() for value in self.items]}


@dataclass(frozen=True, slots=True)
class AtomDraft:
    step: int

    def __post_init__(self) -> None:
        _positive(self.step, "AtomDraft step")

    def to_document(self) -> JSONObject:
        return {"kind": "atom", "step": self.step}


@dataclass(frozen=True, slots=True)
class AllDraft:
    children: tuple[DraftGoal, ...]

    def __post_init__(self) -> None:
        if len(self.children) < 2 or any(not _is_draft_goal(child) for child in self.children):
            raise ValueError("AllDraft requires at least two Goal children")
        _unique_documents(self.children, "AllDraft children")

    def to_document(self) -> JSONObject:
        return {"kind": "all", "children": [child.to_document() for child in self.children]}


@dataclass(frozen=True, slots=True)
class IfDraft:
    condition: PublicValueRef
    operator: ScalarOperator
    value: JSONValue
    then_goal: DraftGoal | None
    else_goal: DraftGoal | None

    def __post_init__(self) -> None:
        if self.condition.kind == "task_literal" or self.operator not in _OPERATORS:
            raise ValueError("IfDraft requires a public condition and supported operator")
        if self.condition.kind == "observation" and self.condition.pointer == "/ok":
            raise ValueError("IfDraft condition must be a business data scalar, not transport ok")
        if isinstance(self.value, (dict, list)) or not is_json_value(self.value):
            raise ValueError("IfDraft comparison value must be a JSON scalar")
        branches = (self.then_goal, self.else_goal)
        if all(branch is None for branch in branches):
            raise ValueError("IfDraft requires at least one branch")
        if any(branch is not None and not _is_draft_goal(branch) for branch in branches):
            raise ValueError("IfDraft branches must be Goals or null")
        object.__setattr__(self, "value", _copy_json(self.value))

    def to_document(self) -> JSONObject:
        return {
            "kind": "if",
            "condition": self.condition.to_document(),
            "operator": self.operator,
            "value": _copy_json(self.value),
            "then_goal": self.then_goal.to_document() if self.then_goal else None,
            "else_goal": self.else_goal.to_document() if self.else_goal else None,
        }


@dataclass(frozen=True, slots=True)
class ForEachDraft:
    members: PublicValueRef
    member_key_pointer: str
    member_argument_pointer: str
    children: tuple[AtomDraft, ...]

    def __post_init__(self) -> None:
        if self.members.kind == "task_literal":
            raise ValueError("ForEachDraft members must be public reset/observation data")
        _pointer(self.member_key_pointer, "ForEach member key pointer")
        _pointer(self.member_argument_pointer, "ForEach member argument pointer")
        if len(self.children) < 2 or any(
            not isinstance(child, AtomDraft) for child in self.children
        ):
            raise ValueError("ForEachDraft requires at least two Atom children")
        _unique_documents(self.children, "ForEachDraft children")

    def to_document(self) -> JSONObject:
        return {
            "kind": "foreach",
            "members": self.members.to_document(),
            "member_key_pointer": self.member_key_pointer,
            "member_argument_pointer": self.member_argument_pointer,
            "children": [child.to_document() for child in self.children],
        }


type DraftGoal = AtomDraft | AllDraft | IfDraft | ForEachDraft


@dataclass(frozen=True, slots=True)
class TaskDraft:
    sampling_target_id: str
    instruction: str
    goal: DraftGoal
    answer: AnswerProjection

    def __post_init__(self) -> None:
        _digest(self.sampling_target_id, "sampling_target_id")
        _text(self.instruction, "TaskDraft instruction")
        if not _is_draft_goal(self.goal) or not isinstance(self.answer, AnswerProjection):
            raise ValueError("TaskDraft requires a Goal and AnswerProjection")

    @property
    def draft_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": TASK_DRAFT_FORMAT,
            "sampling_target_id": self.sampling_target_id,
            "instruction": self.instruction,
            "goal": self.goal.to_document(),
            "answer": self.answer.to_document(),
        }


@dataclass(frozen=True, slots=True)
class MaterializedAnswer:
    value: JSONObject
    schema: JSONObject


def materialize_answer(
    projection: AnswerProjection,
    *,
    reset_observation: JSONValue,
    reset_schema: JSONObject,
    trace: tuple[TraceEvent, ...],
    tool_specs: tuple[ToolSpec | dict[str, Any], ...],
) -> MaterializedAnswer:
    if not isinstance(projection, AnswerProjection) or not is_json_value(reset_observation):
        raise ValueError("materialize_answer received invalid public inputs")
    try:
        validate_schema_document(reset_schema, role="reset schema")
        catalog = validate_tool_catalog(
            tuple(dict(value) for value in tool_specs), role="TaskDraft"
        )
    except (SchemaError, EnvironmentRuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    events = {event.seq: event for event in trace}
    if len(events) != len(trace):
        raise ValueError("answer trace step IDs must be unique")
    value, schema = _materialize(projection, reset_observation, reset_schema, events, catalog)
    if not is_json_object(value):
        raise ValueError("top-level AnswerProjection must resolve to an object")
    return MaterializedAnswer(cast(JSONObject, value), schema)


def sampling_target_from_document(document: Any) -> SamplingTarget:
    value = _exact(
        document,
        {
            "format",
            "required_goal_shape",
            "required_focus_tools",
            "required_outcome",
            "prior_structure_ids",
        },
        "SamplingTarget",
    )
    if value["format"] != SAMPLING_TARGET_FORMAT:
        raise ValueError(f"SamplingTarget format must be {SAMPLING_TARGET_FORMAT!r}")
    return SamplingTarget(
        cast(GoalShape, value["required_goal_shape"]),
        _text_array(value["required_focus_tools"], "required_focus_tools"),
        cast(OutcomeClass, value["required_outcome"]),
        _text_array(value["prior_structure_ids"], "prior_structure_ids"),
    )


def task_draft_from_document(document: Any) -> TaskDraft:
    value = _exact(
        document,
        {"format", "sampling_target_id", "instruction", "goal", "answer"},
        "TaskDraft",
    )
    if value["format"] != TASK_DRAFT_FORMAT:
        raise ValueError(f"TaskDraft format must be {TASK_DRAFT_FORMAT!r}")
    return TaskDraft(
        cast(str, value["sampling_target_id"]),
        cast(str, value["instruction"]),
        _draft_goal_from_document(value["goal"]),
        _projection_from_document(value["answer"]),
    )


def draft_goal_shape(goal: DraftGoal) -> GoalShape:
    if not _is_draft_goal(goal):
        raise TypeError("goal must be a DraftGoal")
    if isinstance(goal, AtomDraft):
        return "atom"
    if isinstance(goal, AllDraft):
        return "all"
    if isinstance(goal, IfDraft):
        return "if"
    return "foreach"


def draft_atom_steps(goal: DraftGoal) -> tuple[int, ...]:
    if isinstance(goal, AtomDraft):
        return (goal.step,)
    if isinstance(goal, AllDraft):
        return tuple(step for child in goal.children for step in draft_atom_steps(child))
    if isinstance(goal, IfDraft):
        branches = (goal.then_goal, goal.else_goal)
        return tuple(
            step for branch in branches if branch is not None for step in draft_atom_steps(branch)
        )
    return tuple(child.step for child in goal.children)


def _materialize(
    projection: AnswerProjection,
    reset: JSONValue,
    reset_schema: JSONObject,
    events: dict[int, TraceEvent],
    catalog: dict[str, ToolSpec],
) -> tuple[JSONValue, JSONObject]:
    if projection.kind == "source":
        value, hint = _resolve_source(
            cast(PublicValueRef, projection.source), reset, reset_schema, events, catalog
        )
        return value, _shape_schema(value, hint)
    if projection.kind == "object":
        object_values: JSONObject = {}
        properties: JSONObject = {}
        for name, child in projection.fields:
            child_value, child_schema = _materialize(child, reset, reset_schema, events, catalog)
            object_values[name], properties[name] = child_value, child_schema
        return object_values, {
            "type": "object",
            "properties": properties,
            "required": list(object_values),
            "additionalProperties": False,
        }
    array_values: list[JSONValue] = []
    schemas: list[JSONObject] = []
    for child in projection.items:
        child_value, child_schema = _materialize(child, reset, reset_schema, events, catalog)
        array_values.append(child_value)
        schemas.append(child_schema)
    unique = {_document_digest(schema): schema for schema in schemas}
    items: JSONObject = (
        next(iter(unique.values()))
        if len(unique) == 1
        else {"anyOf": [unique[key] for key in sorted(unique)]}
    )
    return array_values, {"type": "array", "items": items}


def _resolve_source(
    source: PublicValueRef,
    reset: JSONValue,
    reset_schema: JSONObject,
    events: dict[int, TraceEvent],
    catalog: dict[str, ToolSpec],
) -> tuple[JSONValue, JSONObject | None]:
    if source.kind == "task_literal":
        return _copy_json(source.value), None
    if source.kind == "reset":
        pointer = cast(str, source.pointer)
        return _at(reset, pointer), _schema_at(reset_schema, pointer, reset)
    event = events.get(cast(int, source.step))
    if event is None:
        raise ValueError(f"answer source step {source.step} does not exist")
    pointer = cast(str, source.pointer)
    value = _at(event.observation, pointer)
    spec = catalog.get(event.tool_name)
    if spec is None:
        raise ValueError(f"answer source tool {event.tool_name!r} is not in ToolSpecs")
    if pointer == "/data" or pointer.startswith("/data/"):
        relative = pointer[5:] or ""
        return value, _schema_at(spec["output_schema"], relative, event.observation["data"])
    return value, {"type": "boolean"} if pointer == "/ok" else None


def _shape_schema(value: JSONValue, hint: JSONObject | None) -> JSONObject:
    if isinstance(value, dict):
        properties = hint.get("properties", {}) if isinstance(hint, dict) else {}
        shaped: JSONObject = {}
        for key, child in value.items():
            child_hint = properties.get(key) if isinstance(properties, dict) else None
            shaped[key] = _shape_schema(child, child_hint if isinstance(child_hint, dict) else None)
        return {
            "type": "object",
            "properties": shaped,
            "required": list(value),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item_hint = hint.get("items") if isinstance(hint, dict) else None
        if value:
            schemas = [
                _shape_schema(child, item_hint if isinstance(item_hint, dict) else None)
                for child in value
            ]
            unique = {_document_digest(schema): schema for schema in schemas}
            items: JSONObject = (
                next(iter(unique.values()))
                if len(unique) == 1
                else {"anyOf": [unique[key] for key in sorted(unique)]}
            )
        elif isinstance(item_hint, dict):
            items = _type_only(item_hint)
        else:
            raise ValueError("empty array requires a public source item schema")
        return {"type": "array", "items": items}
    return {"type": _json_type(value)}


def _type_only(schema: JSONObject) -> JSONObject:
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        return {
            "anyOf": [
                _type_only(cast(JSONObject, item)) for item in alternatives if is_json_object(item)
            ]
        }
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return {"type": list(schema_type)}
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        properties = schema.get("properties", {})
        shaped: JSONObject = {
            key: _type_only(value) for key, value in cast(dict[str, JSONObject], properties).items()
        }
        required = schema.get("required", list(shaped))
        return {
            "type": "object",
            "properties": shaped,
            "required": list(cast(list[str], required)),
            "additionalProperties": False,
        }
    if schema_type == "array":
        items = schema.get("items")
        if not is_json_object(items):
            raise ValueError("public source array schema has no item schema")
        return {"type": "array", "items": _type_only(cast(JSONObject, items))}
    if isinstance(schema_type, str):
        return {"type": schema_type}
    raise ValueError("public source schema has no type shape")


def _schema_at(schema: JSONObject, pointer: str, value: JSONValue) -> JSONObject | None:
    current_schema: JSONObject | None = schema
    current_value = value
    for token in _tokens(pointer):
        if isinstance(current_value, dict):
            properties = current_schema.get("properties") if current_schema else None
            child = properties.get(token) if isinstance(properties, dict) else None
            current_schema = cast(JSONObject, child) if is_json_object(child) else None
            current_value = current_value[token]
        elif isinstance(current_value, list):
            child = current_schema.get("items") if current_schema else None
            current_schema = cast(JSONObject, child) if is_json_object(child) else None
            current_value = current_value[int(token)]
        else:
            raise ValueError("schema pointer traverses a scalar")
    return current_schema


def _draft_goal_from_document(document: Any) -> DraftGoal:
    if not is_json_object(document):
        raise ValueError("DraftGoal must be a JSON object")
    kind = document.get("kind")
    if kind == "atom":
        value = _exact(document, {"kind", "step"}, "AtomDraft")
        return AtomDraft(cast(int, value["step"]))
    if kind == "all":
        value = _exact(document, {"kind", "children"}, "AllDraft")
        return AllDraft(
            tuple(_draft_goal_from_document(item) for item in _array(value["children"]))
        )
    if kind == "if":
        value = _exact(
            document,
            {"kind", "condition", "operator", "value", "then_goal", "else_goal"},
            "IfDraft",
        )
        return IfDraft(
            _value_ref_from_document(value["condition"]),
            cast(ScalarOperator, value["operator"]),
            value["value"],
            _draft_goal_from_document(value["then_goal"]) if value["then_goal"] else None,
            _draft_goal_from_document(value["else_goal"]) if value["else_goal"] else None,
        )
    if kind == "foreach":
        value = _exact(
            document,
            {
                "kind",
                "members",
                "member_key_pointer",
                "member_argument_pointer",
                "children",
            },
            "ForEachDraft",
        )
        children = tuple(_draft_goal_from_document(item) for item in _array(value["children"]))
        if any(not isinstance(child, AtomDraft) for child in children):
            raise ValueError("ForEachDraft children must be Atoms")
        return ForEachDraft(
            _value_ref_from_document(value["members"]),
            cast(str, value["member_key_pointer"]),
            cast(str, value["member_argument_pointer"]),
            cast(tuple[AtomDraft, ...], children),
        )
    raise ValueError("DraftGoal has unsupported kind")


def _projection_from_document(document: Any) -> AnswerProjection:
    if not is_json_object(document):
        raise ValueError("AnswerProjection must be a JSON object")
    kind = document.get("kind")
    if kind == "source":
        value = _exact(document, {"kind", "source"}, "source AnswerProjection")
        return AnswerProjection.from_source(_value_ref_from_document(value["source"]))
    if kind == "object":
        value = _exact(document, {"kind", "fields"}, "object AnswerProjection")
        fields = value["fields"]
        if not is_json_object(fields):
            raise ValueError("AnswerProjection fields must be an object")
        return AnswerProjection.from_object(
            {
                key: _projection_from_document(child)
                for key, child in cast(JSONObject, fields).items()
            }
        )
    if kind == "array":
        value = _exact(document, {"kind", "items"}, "array AnswerProjection")
        return AnswerProjection.from_array(
            tuple(_projection_from_document(item) for item in _array(value["items"]))
        )
    raise ValueError("AnswerProjection has unsupported kind")


def _value_ref_from_document(document: Any) -> PublicValueRef:
    if not is_json_object(document):
        raise ValueError("PublicValueRef must be a JSON object")
    kind = document.get("kind")
    if kind == "task_literal":
        value = _exact(document, {"kind", "value"}, "TaskLiteral")
        return PublicValueRef.task_literal(value["value"])
    if kind == "reset":
        value = _exact(document, {"kind", "pointer"}, "ResetValue")
        return PublicValueRef.reset(cast(str, value["pointer"]))
    value = _exact(document, {"kind", "step", "pointer"}, "ObservationValue")
    if value["kind"] != "observation":
        raise ValueError("PublicValueRef has unsupported kind")
    return PublicValueRef.observation(cast(int, value["step"]), cast(str, value["pointer"]))


def _is_draft_goal(value: object) -> bool:
    return isinstance(value, (AtomDraft, AllDraft, IfDraft, ForEachDraft))


def _unique_documents(values: tuple[Any, ...], role: str) -> None:
    identities = [_document_digest(value.to_document()) for value in values]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{role} must be structurally unique")


def _unique_texts(values: tuple[str, ...], role: str, *, empty: bool) -> None:
    if (not empty and not values) or len(values) != len(set(values)):
        raise ValueError(f"{role} must be {'possibly empty ' if empty else ''}unique text")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{role} must contain non-empty text")


def _text_array(value: JSONValue, role: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{role} must be a string array")
    return tuple(cast(list[str], value))


def _array(value: JSONValue) -> list[JSONValue]:
    if not isinstance(value, list):
        raise ValueError("expected an array")
    return value


def _at(document: JSONValue, pointer: str) -> JSONValue:
    current = document
    for token in _tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise ValueError("JSON pointer traverses a scalar")
    return _copy_json(current)


def _pointer(value: str | None, role: str) -> None:
    if not isinstance(value, str) or value != "" and not value.startswith("/"):
        raise ValueError(f"{role} must be an RFC 6901 pointer")
    _tokens(value)


def _tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _json_type(value: JSONValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ValueError(f"{role} has invalid fields: expected {sorted(keys)}, got {actual}")
    return cast(JSONObject, document)


def _positive(value: int | None, role: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


def _text(value: str, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _digest(value: str, role: str) -> None:
    try:
        _hex_digest(value, field=role)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _document_digest(document: JSONObject) -> str:
    return sha256_hex(canonical_bytes(document))


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


__all__ = [
    "SAMPLING_TARGET_FORMAT",
    "TASK_DRAFT_FORMAT",
    "AllDraft",
    "AnswerProjection",
    "AtomDraft",
    "ForEachDraft",
    "IfDraft",
    "MaterializedAnswer",
    "PublicValueRef",
    "SamplingTarget",
    "TaskDraft",
    "draft_atom_steps",
    "draft_goal_shape",
    "materialize_answer",
    "sampling_target_from_document",
    "task_draft_from_document",
]

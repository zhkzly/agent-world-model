"""Shared deterministic validation for public AnswerField sources."""

from __future__ import annotations

import json
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.semantics import CapabilitySpec

_TOOL_ERROR_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {},
    },
    "required": ["code", "message"],
    "additionalProperties": False,
}


class AnswerSourceContractError(ValueError):
    def __init__(
        self,
        capability_id: str,
        field_id: str,
        source: JSONObject,
        original: Exception,
    ) -> None:
        self.details: dict[str, Any] = {
            "capability_id": capability_id,
            "field_id": field_id,
            "source": source,
            "original_code": type(original).__name__,
            "original_message": str(original),
        }
        super().__init__(json.dumps(self.details, ensure_ascii=False, sort_keys=True))


def validate_answer_field_source_contract(
    capabilities: tuple[CapabilitySpec, ...],
    surface: PublicSurfaceManifest,
) -> None:
    """Bind every AnswerField declaration to one real public schema source."""

    tools = {item["name"]: item for item in surface.tool_specs}
    for capability in capabilities:
        for field in capability.answer_fields:
            source = field.public_source
            try:
                _answer_source_schema(capability, source, surface, tools)
                if source.kind in {"task_literal", "tool_schema_constant"}:
                    validate_instance(
                        source.value,
                        field.schema,
                        role=(
                            f"capability {capability.capability_id!r} answer field "
                            f"{field.field_id!r} source value"
                        ),
                    )
            except (KeyError, SchemaError, TypeError, ValueError) as exc:
                raise AnswerSourceContractError(
                    capability.capability_id,
                    field.field_id,
                    source.to_document(),
                    exc,
                ) from exc


def _answer_source_schema(
    capability: CapabilitySpec,
    source: Any,
    surface: PublicSurfaceManifest,
    tools: dict[str, ToolSpec],
) -> dict[str, Any]:
    if source.kind == "task_literal":
        return {}
    pointer = cast(str, source.json_pointer)
    if source.kind == "task_descriptor":
        return _schema_at_public_pointer(capability.public_descriptor_schema, pointer)
    if source.kind == "reset":
        return _schema_at_public_pointer(surface.reset_observation_schema, pointer)
    tool = tools[cast(str, source.tool_name)]
    if source.kind == "tool_schema_constant":
        schema = _schema_at_public_pointer(tool["input_schema"], pointer)
        constant = schema.get("const")
        enum = schema.get("enum")
        is_constant = ("const" in schema and same_json(constant, source.value)) or (
            isinstance(enum, list) and len(enum) == 1 and same_json(enum[0], source.value)
        )
        if not is_constant:
            raise ValueError("tool_schema_constant pointer is not an exact const or singleton enum")
        return schema
    if source.kind != "tool_observation":
        raise ValueError(f"unsupported AnswerField source kind {source.kind!r}")
    tokens = _pointer_tokens(pointer)
    if not tokens:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "data": {"anyOf": [tool["output_schema"], {"type": "null"}]},
                "error": {"anyOf": [_TOOL_ERROR_SCHEMA, {"type": "null"}]},
            },
            "required": ["ok", "data", "error"],
            "additionalProperties": False,
        }
    head, *tail = tokens
    relative = "" if not tail else "/" + "/".join(_escape_pointer_token(item) for item in tail)
    if head == "ok":
        if tail:
            raise ValueError("tool observation ok is scalar")
        return {"type": "boolean"}
    if head == "data":
        return _schema_at_public_pointer(tool["output_schema"], relative)
    if head == "error":
        return _schema_at_public_pointer(_TOOL_ERROR_SCHEMA, relative)
    raise ValueError("tool observation pointer must start at /ok, /data, or /error")


def _schema_at_public_pointer(schema: JSONObject, pointer: str) -> dict[str, Any]:
    current: Any = schema
    root: Any = schema
    seen_refs: set[str] = set()
    for token in _pointer_tokens(pointer):
        current = _dereference_local_schema(current, root, seen_refs)
        if not isinstance(current, dict):
            raise TypeError("schema pointer traverses a non-object schema")
        properties = current.get("properties")
        if isinstance(properties, dict) and token in properties:
            current = properties[token]
            continue
        items = current.get("items")
        if isinstance(items, dict) and token.isdigit():
            current = items
            continue
        raise KeyError(token)
    current = _dereference_local_schema(current, root, seen_refs)
    if not isinstance(current, dict):
        raise TypeError("schema pointer does not resolve to a schema object")
    return cast(dict[str, Any], current)


def _dereference_local_schema(current: Any, root: Any, seen: set[str]) -> Any:
    while isinstance(current, dict) and isinstance(current.get("$ref"), str):
        reference = cast(str, current["$ref"])
        if not reference.startswith("#") or reference in seen:
            raise ValueError("schema source contains an invalid or cyclic local reference")
        seen.add(reference)
        current = json_pointer_value(root, reference.removeprefix("#"))
    return current


def json_pointer_value(value: Any, pointer: str) -> JSONValue:
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise TypeError("JSON pointer traverses a scalar")
    return cast(JSONValue, current)


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("not an RFC 6901 pointer")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def same_json(left: Any, right: Any) -> bool:
    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except (TypeError, ValueError):
        return False


__all__ = [
    "AnswerSourceContractError",
    "json_pointer_value",
    "same_json",
    "validate_answer_field_source_contract",
]

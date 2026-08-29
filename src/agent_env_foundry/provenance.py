"""Exact public provenance for argument leaves in a tool episode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec, validate_tool_catalog
from agent_env_foundry.jsonvalue import is_json_value
from agent_env_foundry.semantics import TraceEvent

ArgumentSourceKind = Literal[
    "task_literal",
    "reset",
    "tool_observation",
    "tool_schema_constant",
    "agent_choice",
]


class ProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArgumentProvenance:
    event_seq: int
    argument_pointer: str
    value: JSONValue
    source_kind: ArgumentSourceKind
    source_event_seq: int | None
    source_tool_name: str | None
    source_pointer: str | None

    def __post_init__(self) -> None:
        if self.event_seq <= 0 or not self.argument_pointer.startswith("/"):
            raise ProvenanceError("argument occurrence is invalid")
        if not is_json_value(self.value):
            raise ProvenanceError("argument occurrence value is not JSON")
        if self.source_kind == "tool_observation":
            if (
                self.source_event_seq is None
                or self.source_event_seq >= self.event_seq
                or not self.source_tool_name
                or not self.source_pointer
            ):
                raise ProvenanceError("tool observation provenance is incomplete or not prior")
        elif self.source_kind == "tool_schema_constant":
            if (
                self.source_event_seq is not None
                or not self.source_tool_name
                or not self.source_pointer
            ):
                raise ProvenanceError("tool schema constant provenance is incomplete")
        elif self.source_kind in {"task_literal", "reset"}:
            if (
                self.source_event_seq is not None
                or self.source_tool_name is not None
                or not self.source_pointer
            ):
                raise ProvenanceError(f"{self.source_kind} provenance is incomplete")
        elif self.source_kind == "agent_choice":
            if any(
                item is not None
                for item in (self.source_event_seq, self.source_tool_name, self.source_pointer)
            ):
                raise ProvenanceError("agent choice cannot claim another public source")
        else:
            raise ProvenanceError(f"unknown argument source kind {self.source_kind!r}")

    def to_document(self) -> JSONObject:
        return {
            "event_seq": self.event_seq,
            "argument_pointer": self.argument_pointer,
            "value": self.value,
            "source_kind": self.source_kind,
            "source_event_seq": self.source_event_seq,
            "source_tool_name": self.source_tool_name,
            "source_pointer": self.source_pointer,
        }


def resolve_argument_provenance(
    *,
    trace: tuple[TraceEvent, ...],
    instruction_values: JSONObject,
    reset_observation: JSONValue,
    tool_specs: tuple[ToolSpec, ...],
) -> tuple[ArgumentProvenance, ...]:
    """Resolve every argument leaf without reading protected/native state or error prose."""

    catalog = validate_tool_catalog(tool_specs, role="argument provenance tools")
    instruction_leaves = _leaf_items(instruction_values, "/public_descriptor")
    reset_leaves = _leaf_items(reset_observation, "")
    records: list[ArgumentProvenance] = []
    prior_successes: list[tuple[int, str, tuple[tuple[str, JSONValue], ...]]] = []

    for event in trace:
        spec = catalog.get(event.tool_name)
        if spec is None:
            raise ProvenanceError(f"trace uses unknown tool {event.tool_name!r}")
        for pointer, value in _leaf_items(event.arguments, ""):
            instruction_pointer = _matching_pointer(instruction_leaves, value)
            if instruction_pointer is not None:
                records.append(
                    _record(event, pointer, value, "task_literal", None, None, instruction_pointer)
                )
                continue

            observed = _latest_observation(prior_successes, value)
            if observed is not None:
                source_seq, source_tool, source_pointer = observed
                records.append(
                    _record(
                        event,
                        pointer,
                        value,
                        "tool_observation",
                        source_seq,
                        source_tool,
                        source_pointer,
                    )
                )
                continue

            reset_pointer = _matching_pointer(reset_leaves, value)
            if reset_pointer is not None:
                records.append(_record(event, pointer, value, "reset", None, None, reset_pointer))
                continue

            if _schema_constant(spec["input_schema"], pointer, value):
                records.append(
                    _record(
                        event,
                        pointer,
                        value,
                        "tool_schema_constant",
                        None,
                        event.tool_name,
                        pointer,
                    )
                )
                continue

            records.append(_record(event, pointer, value, "agent_choice", None, None, None))

        observation = event.observation
        if observation.get("ok") is True and "data" in observation:
            prior_successes.append(
                (event.seq, event.tool_name, _leaf_items(observation["data"], "/data"))
            )

    resolved = tuple(records)
    validate_argument_provenance(trace, resolved)
    return resolved


def validate_argument_provenance(
    trace: tuple[TraceEvent, ...],
    provenance: tuple[ArgumentProvenance, ...],
) -> None:
    expected = {
        (event.seq, pointer): value
        for event in trace
        for pointer, value in _leaf_items(event.arguments, "")
    }
    actual = {(item.event_seq, item.argument_pointer): item for item in provenance}
    if len(actual) != len(provenance) or set(actual) != set(expected):
        raise ProvenanceError("argument provenance must cover every argument leaf exactly once")
    events = {event.seq: event for event in trace}
    for key, item in actual.items():
        if not _same_leaf(item.value, expected[key]):
            raise ProvenanceError("argument provenance value differs from the trace")
        if item.source_kind != "tool_observation":
            continue
        assert item.source_event_seq is not None
        assert item.source_pointer is not None
        source_event = events.get(item.source_event_seq)
        if source_event is None or source_event.observation.get("ok") is not True:
            raise ProvenanceError("tool provenance does not name a prior successful observation")
        try:
            source_value = _resolve_pointer(source_event.observation, item.source_pointer)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProvenanceError("tool provenance pointer does not resolve") from exc
        if not _same_leaf(item.value, source_value):
            raise ProvenanceError("tool provenance value differs from its observation occurrence")


def _record(
    event: TraceEvent,
    pointer: str,
    value: JSONValue,
    kind: ArgumentSourceKind,
    source_event_seq: int | None,
    source_tool_name: str | None,
    source_pointer: str | None,
) -> ArgumentProvenance:
    return ArgumentProvenance(
        event.seq,
        pointer,
        value,
        kind,
        source_event_seq,
        source_tool_name,
        source_pointer,
    )


def _latest_observation(
    prior: list[tuple[int, str, tuple[tuple[str, JSONValue], ...]]],
    value: JSONValue,
) -> tuple[int, str, str] | None:
    for seq, tool_name, leaves in reversed(prior):
        pointer = _matching_pointer(leaves, value)
        if pointer is not None:
            return seq, tool_name, pointer
    return None


def _matching_pointer(
    leaves: tuple[tuple[str, JSONValue], ...],
    value: JSONValue,
) -> str | None:
    return next((pointer for pointer, item in leaves if _same_leaf(item, value)), None)


def _leaf_items(value: JSONValue, prefix: str) -> tuple[tuple[str, JSONValue], ...]:
    leaves: list[tuple[str, JSONValue]] = []

    def visit(item: JSONValue, path: str) -> None:
        if isinstance(item, dict):
            for key in sorted(item):
                visit(item[key], f"{path}/{_escape(key)}")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}/{index}")
            return
        leaves.append((path, item))

    visit(value, prefix)
    return tuple(leaves)


def _schema_constant(schema: JSONObject, pointer: str, value: JSONValue) -> bool:
    current: Any = schema
    try:
        for token in _tokens(pointer):
            if not isinstance(current, dict):
                return False
            if "properties" in current and isinstance(current["properties"], dict):
                current = current["properties"][token]
            elif "items" in current:
                int(token)
                current = current["items"]
            else:
                return False
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(current, dict):
        return False
    if "const" in current and is_json_value(current["const"]):
        return _same_leaf(cast(JSONValue, current["const"]), value)
    enum = current.get("enum")
    return (
        isinstance(enum, list)
        and len(enum) == 1
        and is_json_value(enum[0])
        and _same_leaf(cast(JSONValue, enum[0]), value)
    )


def _resolve_pointer(value: JSONValue, pointer: str) -> JSONValue:
    current = value
    for token in _tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise TypeError("pointer traverses a scalar")
    return current


def _tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("not an RFC 6901 pointer")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _same_leaf(left: JSONValue, right: JSONValue) -> bool:
    return type(left) is type(right) and left == right


__all__ = [
    "ArgumentProvenance",
    "ArgumentSourceKind",
    "ProvenanceError",
    "resolve_argument_provenance",
    "validate_argument_provenance",
]

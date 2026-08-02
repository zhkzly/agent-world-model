from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

RUNTIME_ABI_VERSION = "agent-world.runtime.v2"

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class RuntimeOperation(StrEnum):
    HANDSHAKE = "handshake"
    RESET = "reset"
    INVOKE = "invoke"
    SNAPSHOT = "snapshot"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class ProtocolLimits:
    max_message_bytes: int = 1024 * 1024
    max_nesting_depth: int = 64
    max_container_items: int = 10_000
    max_string_chars: int = 512 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("max_message_bytes", self.max_message_bytes),
            ("max_nesting_depth", self.max_nesting_depth),
            ("max_container_items", self.max_container_items),
            ("max_string_chars", self.max_string_chars),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")


DEFAULT_PROTOCOL_LIMITS = ProtocolLimits()


class ProtocolViolation(RuntimeError):
    """A candidate emitted or was about to receive an invalid ABI message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        request_id: str = "",
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": str(self),
            "request_id": self.request_id,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class RuntimeErrorDetail:
    code: str
    message: str
    retryable: bool
    details: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    request_id: str
    operation: RuntimeOperation
    payload: Mapping[str, JsonValue]
    abi_version: str = RUNTIME_ABI_VERSION

    def to_wire(self) -> dict[str, JsonValue]:
        return {
            "abi_version": self.abi_version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class RuntimeResponse:
    request_id: str
    operation: RuntimeOperation
    ok: bool
    result: Mapping[str, JsonValue] | None = None
    error: RuntimeErrorDetail | None = None
    abi_version: str = RUNTIME_ABI_VERSION


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACTOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

# These *exact* names belong to framework-private evaluation contracts. They
# are rejected recursively, including inside reset config and tool arguments.
# A name is not private merely because it looks like an identifier: ordinary
# WorldSpec schemas may legitimately use ``task_id`` for a domain object. The
# actual trust boundary is the typed task/verifier projection; this list is
# only a final defence against serialising a framework-private object wholesale.
_PRIVATE_RUNTIME_KEYS = frozenset(
    {
        "case",
        "case_id",
        "case_label",
        "framework_private",
        "evaluator_goal",
        "evaluation_witness",
        "expected_answer",
        "expected_state",
        "expected_state_delta",
        "expected_path",
        "expected_output",
        "oracle",
        "oracle_data",
        "sealed",
        "sealed_case",
        "sealed_data",
        "verifier",
        "verifier_ir",
        "verifier_spec",
        "release_decision",
        "release_label",
        "release_threshold",
    }
)


def new_request_id() -> str:
    return f"req-{uuid4().hex}"


def make_request(
    operation: RuntimeOperation | str,
    payload: Mapping[str, JsonValue] | None = None,
    *,
    request_id: str | None = None,
    limits: ProtocolLimits = DEFAULT_PROTOCOL_LIMITS,
) -> RuntimeRequest:
    try:
        parsed_operation = RuntimeOperation(operation)
    except ValueError as exc:
        raise ProtocolViolation(
            "unsupported_operation", f"unsupported runtime operation: {operation!r}"
        ) from exc
    request = RuntimeRequest(
        request_id=request_id or new_request_id(),
        operation=parsed_operation,
        payload=dict(payload or {}),
    )
    validate_request(request, limits=limits)
    return request


def validate_request(
    request: RuntimeRequest, *, limits: ProtocolLimits = DEFAULT_PROTOCOL_LIMITS
) -> None:
    if request.abi_version != RUNTIME_ABI_VERSION:
        raise ProtocolViolation(
            "abi_version_mismatch",
            f"request ABI must be {RUNTIME_ABI_VERSION}",
            request_id=request.request_id,
        )
    _validate_request_id(request.request_id)
    _validate_json_value(request.payload, limits=limits, path="payload")
    _reject_private_runtime_keys(request.payload, path="payload")

    payload = request.payload
    if request.operation in {
        RuntimeOperation.HANDSHAKE,
        RuntimeOperation.SNAPSHOT,
        RuntimeOperation.CLOSE,
    }:
        _require_exact_keys(
            payload, required=set(), optional=set(), path=f"payload[{request.operation.value}]"
        )
        return
    if request.operation is RuntimeOperation.RESET:
        _require_exact_keys(
            payload,
            required={"seed", "actor", "config"},
            optional=set(),
            path="payload[reset]",
        )
        seed = payload["seed"]
        if isinstance(seed, bool) or not isinstance(seed, (int, str)):
            raise ProtocolViolation(
                "invalid_reset_seed",
                "reset seed must be an integer or string",
                request_id=request.request_id,
            )
        if isinstance(seed, str) and not seed:
            raise ProtocolViolation(
                "invalid_reset_seed", "reset seed must not be empty", request_id=request.request_id
            )
        actor = payload["actor"]
        if not isinstance(actor, str) or not _ACTOR_ID_RE.fullmatch(actor):
            raise ProtocolViolation(
                "invalid_reset_actor",
                "reset actor must be a valid framework actor id",
                request_id=request.request_id,
            )
        if not isinstance(payload["config"], Mapping):
            raise ProtocolViolation(
                "invalid_reset_config",
                "reset config must be an object",
                request_id=request.request_id,
            )
        return
    if request.operation is RuntimeOperation.INVOKE:
        _require_exact_keys(
            payload,
            required={"tool", "args", "idempotency_key"},
            optional=set(),
            path="payload[invoke]",
        )
        tool = payload["tool"]
        if not isinstance(tool, str) or not _TOOL_NAME_RE.fullmatch(tool):
            raise ProtocolViolation(
                "invalid_tool_name",
                "invoke tool has an invalid name",
                request_id=request.request_id,
            )
        if not isinstance(payload["args"], Mapping):
            raise ProtocolViolation(
                "invalid_tool_arguments",
                "invoke args must be an object",
                request_id=request.request_id,
            )
        idempotency_key = payload["idempotency_key"]
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > 256
        ):
            raise ProtocolViolation(
                "invalid_idempotency_key",
                "idempotency_key must be a non-empty string of at most 256 characters",
                request_id=request.request_id,
            )


def encode_request(
    request: RuntimeRequest, *, limits: ProtocolLimits = DEFAULT_PROTOCOL_LIMITS
) -> bytes:
    validate_request(request, limits=limits)
    try:
        encoded = (
            json.dumps(
                request.to_wire(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation(
            "request_not_json",
            f"runtime request is not strict JSON: {exc}",
            request_id=request.request_id,
        ) from exc
    if len(encoded) > limits.max_message_bytes:
        raise ProtocolViolation(
            "request_too_large",
            f"runtime request exceeds {limits.max_message_bytes} bytes",
            request_id=request.request_id,
            details={"size_bytes": len(encoded)},
        )
    return encoded


def decode_response(
    raw: bytes,
    *,
    expected_request: RuntimeRequest,
    limits: ProtocolLimits = DEFAULT_PROTOCOL_LIMITS,
) -> RuntimeResponse:
    if not raw.endswith(b"\n"):
        raise ProtocolViolation(
            "unterminated_response",
            "runtime response must be one newline-terminated JSON object",
            request_id=expected_request.request_id,
        )
    if len(raw) > limits.max_message_bytes:
        raise ProtocolViolation(
            "response_too_large",
            f"runtime response exceeds {limits.max_message_bytes} bytes",
            request_id=expected_request.request_id,
            details={"size_bytes": len(raw)},
        )
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolViolation(
            "response_not_utf8",
            "runtime response must be UTF-8",
            request_id=expected_request.request_id,
        ) from exc
    if not text.strip():
        raise ProtocolViolation(
            "empty_response",
            "runtime returned an empty JSONL record",
            request_id=expected_request.request_id,
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json,
        )
    except RecursionError as exc:
        raise ProtocolViolation(
            "json_too_deep",
            "runtime response exceeds JSON parser nesting limits",
            request_id=expected_request.request_id,
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProtocolViolation(
            "malformed_response_json",
            f"runtime response is not strict JSON: {exc}",
            request_id=expected_request.request_id,
        ) from exc
    if not isinstance(value, dict):
        raise ProtocolViolation(
            "response_not_object",
            "runtime response must be a JSON object",
            request_id=expected_request.request_id,
        )
    _validate_json_value(value, limits=limits, path="response")
    _reject_private_runtime_keys(value, path="response")
    _require_exact_keys(
        value,
        required={"abi_version", "request_id", "operation", "ok"},
        optional={"result", "error"},
        path="response",
    )

    if value["abi_version"] != RUNTIME_ABI_VERSION:
        raise ProtocolViolation(
            "abi_version_mismatch",
            f"runtime response ABI must be {RUNTIME_ABI_VERSION}",
            request_id=expected_request.request_id,
        )
    if value["request_id"] != expected_request.request_id:
        raise ProtocolViolation(
            "request_id_mismatch",
            "runtime response request_id does not match the in-flight request",
            request_id=expected_request.request_id,
            details={"actual_request_id": str(value["request_id"])},
        )
    if value["operation"] != expected_request.operation.value:
        raise ProtocolViolation(
            "operation_mismatch",
            "runtime response operation does not match the in-flight request",
            request_id=expected_request.request_id,
            details={"actual_operation": str(value["operation"])},
        )
    if not isinstance(value["ok"], bool):
        raise ProtocolViolation(
            "invalid_response_status",
            "runtime response ok must be a boolean",
            request_id=expected_request.request_id,
        )

    if value["ok"]:
        if "error" in value and value["error"] is not None:
            raise ProtocolViolation(
                "ambiguous_response",
                "successful response must not contain an error",
                request_id=expected_request.request_id,
            )
        result = value.get("result")
        if not isinstance(result, dict):
            raise ProtocolViolation(
                "invalid_response_result",
                "successful response result must be an object",
                request_id=expected_request.request_id,
            )
        if expected_request.operation is RuntimeOperation.HANDSHAKE:
            _validate_handshake_result(result, request_id=expected_request.request_id)
        else:
            _validate_operation_result(
                expected_request.operation,
                result,
                request_id=expected_request.request_id,
            )
        return RuntimeResponse(
            request_id=expected_request.request_id,
            operation=expected_request.operation,
            ok=True,
            result=result,
        )

    failure_result: Mapping[str, JsonValue] | None = None
    if expected_request.operation is RuntimeOperation.INVOKE:
        raw_failure_result = value.get("result")
        if not isinstance(raw_failure_result, dict):
            raise ProtocolViolation(
                "missing_failure_observation",
                "failed invoke must contain the standard result envelope",
                request_id=expected_request.request_id,
            )
        _validate_operation_result(
            RuntimeOperation.INVOKE,
            raw_failure_result,
            request_id=expected_request.request_id,
        )
        failure_result = raw_failure_result
    elif "result" in value and value["result"] is not None:
        raise ProtocolViolation(
            "ambiguous_response",
            "failed non-invoke response must not contain a result",
            request_id=expected_request.request_id,
        )
    error = value.get("error")
    if not isinstance(error, dict):
        raise ProtocolViolation(
            "missing_runtime_error",
            "failed response must contain an error object",
            request_id=expected_request.request_id,
        )
    _require_exact_keys(
        error,
        required={"code", "message", "retryable"},
        optional={"details"},
        path="response.error",
    )
    if not isinstance(error["code"], str) or not _ERROR_CODE_RE.fullmatch(error["code"]):
        raise ProtocolViolation(
            "invalid_runtime_error",
            "runtime error code is invalid",
            request_id=expected_request.request_id,
        )
    if not isinstance(error["message"], str) or not error["message"]:
        raise ProtocolViolation(
            "invalid_runtime_error",
            "runtime error message must be non-empty",
            request_id=expected_request.request_id,
        )
    if not isinstance(error["retryable"], bool):
        raise ProtocolViolation(
            "invalid_runtime_error",
            "runtime error retryable must be boolean",
            request_id=expected_request.request_id,
        )
    details = error.get("details", {})
    if not isinstance(details, dict):
        raise ProtocolViolation(
            "invalid_runtime_error",
            "runtime error details must be an object",
            request_id=expected_request.request_id,
        )
    if details:
        raise ProtocolViolation(
            "unmodeled_error_details",
            "runtime error details must be empty in the closed agent-facing ABI",
            request_id=expected_request.request_id,
        )
    return RuntimeResponse(
        request_id=expected_request.request_id,
        operation=expected_request.operation,
        ok=False,
        result=failure_result,
        error=RuntimeErrorDetail(
            code=error["code"],
            message=error["message"],
            retryable=error["retryable"],
            details=details,
        ),
    )


def _validate_handshake_result(result: Mapping[str, JsonValue], *, request_id: str) -> None:
    _require_exact_keys(
        result,
        required={"runtime_id", "operations", "tools"},
        optional={"metadata"},
        path="response.result[handshake]",
    )
    runtime_id = result["runtime_id"]
    if not isinstance(runtime_id, str) or not runtime_id or len(runtime_id) > 256:
        raise ProtocolViolation(
            "invalid_handshake", "handshake runtime_id is invalid", request_id=request_id
        )
    operations = result["operations"]
    if not isinstance(operations, list) or not all(isinstance(item, str) for item in operations):
        raise ProtocolViolation(
            "invalid_handshake",
            (
                "response.result[handshake].operations must be the JSON string array "
                '["handshake","reset","invoke","snapshot","close"], '
                "not operation objects"
            ),
            request_id=request_id,
        )
    if set(operations) != {operation.value for operation in RuntimeOperation} or len(
        operations
    ) != len(RuntimeOperation):
        raise ProtocolViolation(
            "incomplete_handshake",
            (
                "response.result[handshake].operations must contain each ABI v2 string exactly "
                'once: ["handshake","reset","invoke","snapshot","close"]'
            ),
            request_id=request_id,
        )
    tools = result["tools"]
    if not isinstance(tools, list) or not all(isinstance(item, dict) for item in tools):
        raise ProtocolViolation(
            "invalid_handshake",
            "handshake tools must be a list of tool contract objects",
            request_id=request_id,
        )
    # Report one complete, bounded key-shape diagnosis before reading any
    # individual tool fields.  A generated Runtime commonly constructs every
    # tool from the same source record; stopping at tools[0] turns one
    # mechanical projection mistake into an expensive repair-by-repair loop.
    required_tool_keys = {
        "tool_id",
        "namespace",
        "name",
        "input_schema",
        "output_schema",
        "observation_schema",
    }
    allowed_tool_keys = required_tool_keys | {"description"}
    key_issue_indexes: dict[tuple[tuple[str, ...], tuple[str, ...]], list[int]] = {}
    for index, tool in enumerate(tools):
        assert isinstance(tool, dict)
        keys = set(tool)
        missing = tuple(sorted(required_tool_keys - keys))
        extra = tuple(sorted(keys - allowed_tool_keys))
        if missing or extra:
            key_issue_indexes.setdefault((missing, extra), []).append(index)
    if key_issue_indexes:
        issue_groups: list[dict[str, JsonValue]] = []
        for (missing, extra), indexes in sorted(key_issue_indexes.items()):
            issue_groups.append(
                {
                    "count": len(indexes),
                    "sample_indexes": cast(list[JsonValue], indexes[:8]),
                    "missing": cast(list[JsonValue], list(missing)),
                    "extra": cast(list[JsonValue], list(extra)),
                }
            )
        all_missing = sorted({field for missing, _extra in key_issue_indexes for field in missing})
        all_extra = sorted({field for _missing, extra in key_issue_indexes for field in extra})
        issue_count = sum(len(indexes) for indexes in key_issue_indexes.values())
        raise ProtocolViolation(
            "schema_mismatch",
            (
                "response.result[handshake].tools have invalid keys in "
                f"{issue_count} entries; check every tools[] entry against the "
                "implementation-contract handshake fields "
                "(tool_id, namespace, name, input_schema, output_schema, "
                "observation_schema; optional description)"
            ),
            request_id=request_id,
            details={
                "missing": cast(list[JsonValue], all_missing),
                "extra": cast(list[JsonValue], all_extra),
                "tool_key_issue_groups": cast(list[JsonValue], issue_groups),
            },
        )
    tool_ids: list[str] = []
    for index, tool in enumerate(tools):
        assert isinstance(tool, dict)
        tool_id = tool["tool_id"]
        if not isinstance(tool_id, str) or not _TOOL_NAME_RE.fullmatch(tool_id):
            raise ProtocolViolation(
                "invalid_handshake",
                f"handshake tool {index} has an invalid tool_id",
                request_id=request_id,
            )
        tool_ids.append(tool_id)
        namespace = tool["namespace"]
        name = tool["name"]
        if (
            not isinstance(namespace, str)
            or not _TOOL_NAME_RE.fullmatch(namespace)
            or not isinstance(name, str)
            or not _TOOL_NAME_RE.fullmatch(name)
            or tool_id != f"{namespace}.{name}"
        ):
            raise ProtocolViolation(
                "invalid_handshake",
                f"handshake tool {tool_id} namespace/name do not match tool_id",
                request_id=request_id,
            )
        for schema_name in ("input_schema", "output_schema", "observation_schema"):
            schema = tool[schema_name]
            if not isinstance(schema, dict):
                raise ProtocolViolation(
                    "invalid_handshake",
                    f"handshake tool {tool_id} {schema_name} must be an object",
                    request_id=request_id,
                )
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ProtocolViolation(
                    "invalid_handshake",
                    f"handshake tool {tool_id} {schema_name} is not valid JSON Schema",
                    request_id=request_id,
                ) from exc
    if len(set(tool_ids)) != len(tool_ids):
        raise ProtocolViolation(
            "invalid_handshake",
            "handshake tool_id values must be unique",
            request_id=request_id,
        )
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ProtocolViolation(
            "invalid_handshake", "handshake metadata must be an object", request_id=request_id
        )


def _validate_operation_result(
    operation: RuntimeOperation,
    result: Mapping[str, JsonValue],
    *,
    request_id: str,
) -> None:
    if operation is RuntimeOperation.RESET:
        _require_exact_keys(
            result,
            required={"observation", "state_digest", "terminated", "info"},
            optional=set(),
            path="response.result[reset]",
        )
        _require_object(result["observation"], "reset observation", request_id)
        _require_digest(result["state_digest"], request_id)
        _require_boolean(result["terminated"], "reset terminated", request_id)
        _require_object(result["info"], "reset info", request_id)
        if result["info"]:
            raise ProtocolViolation(
                "unmodeled_reset_info",
                "reset info must be empty in the closed agent-facing ABI",
                request_id=request_id,
            )
        return
    if operation is RuntimeOperation.INVOKE:
        _require_exact_keys(
            result,
            required={
                "tool_result",
                "observation",
                "events",
                "state_digest",
                "reward",
                "terminated",
                "truncated",
                "info",
            },
            optional=set(),
            path="response.result[invoke]",
        )
        _require_object(result["observation"], "invoke observation", request_id)
        if not isinstance(result["events"], list):
            raise ProtocolViolation(
                "invalid_invoke_result",
                "invoke events must be an array",
                request_id=request_id,
            )
        if result["events"]:
            raise ProtocolViolation(
                "unmodeled_invoke_events",
                "invoke events must be empty in the closed agent-facing ABI",
                request_id=request_id,
            )
        _require_digest(result["state_digest"], request_id)
        reward = result["reward"]
        if (
            isinstance(reward, bool)
            or not isinstance(reward, (int, float))
            or not math.isfinite(float(reward))
        ):
            raise ProtocolViolation(
                "invalid_invoke_result",
                "invoke reward must be a finite number",
                request_id=request_id,
            )
        _require_boolean(result["terminated"], "invoke terminated", request_id)
        _require_boolean(result["truncated"], "invoke truncated", request_id)
        _require_object(result["info"], "invoke info", request_id)
        if result["info"]:
            raise ProtocolViolation(
                "unmodeled_invoke_info",
                "invoke info must be empty in the closed agent-facing ABI",
                request_id=request_id,
            )
        return
    if operation is RuntimeOperation.SNAPSHOT:
        _require_exact_keys(
            result,
            required={"observation", "state_digest"},
            optional=set(),
            path="response.result[snapshot]",
        )
        _require_object(result["observation"], "snapshot observation", request_id)
        _require_digest(result["state_digest"], request_id)
        return
    if operation is RuntimeOperation.CLOSE:
        _require_exact_keys(
            result,
            required=set(),
            optional=set(),
            path="response.result[close]",
        )


def _require_object(value: JsonValue, label: str, request_id: str) -> None:
    if not isinstance(value, dict):
        raise ProtocolViolation(
            "invalid_operation_result",
            f"{label} must be an object",
            request_id=request_id,
        )


def _require_boolean(value: JsonValue, label: str, request_id: str) -> None:
    if not isinstance(value, bool):
        raise ProtocolViolation(
            "invalid_operation_result",
            f"{label} must be a boolean",
            request_id=request_id,
        )


def _require_digest(value: JsonValue, request_id: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ProtocolViolation(
            "invalid_state_digest",
            "state_digest must match sha256:<64 lowercase hexadecimal characters>",
            request_id=request_id,
        )


def _validate_request_id(value: str) -> None:
    if not isinstance(value, str) or not _REQUEST_ID_RE.fullmatch(value):
        raise ProtocolViolation(
            "invalid_request_id", "request_id has an invalid format", request_id=str(value)
        )


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing or extra:
        missing_details: list[JsonValue] = []
        missing_details.extend(missing)
        extra_details: list[JsonValue] = []
        extra_details.extend(extra)
        raise ProtocolViolation(
            "schema_mismatch",
            f"{path} has invalid keys",
            details={"missing": missing_details, "extra": extra_details},
        )


def _validate_json_value(value: Any, *, limits: ProtocolLimits, path: str, depth: int = 0) -> None:
    if depth > limits.max_nesting_depth:
        raise ProtocolViolation("json_too_deep", f"{path} exceeds JSON nesting limit")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolViolation("non_finite_number", f"{path} contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > limits.max_string_chars:
            raise ProtocolViolation("string_too_large", f"{path} contains an oversized string")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ProtocolViolation(
                "invalid_unicode", f"{path} contains an isolated Unicode surrogate"
            )
        return
    if isinstance(value, Mapping):
        if len(value) > limits.max_container_items:
            raise ProtocolViolation(
                "container_too_large", f"{path} contains too many object members"
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolViolation(
                    "non_string_key", f"{path} contains a non-string object key"
                )
            _validate_json_value(item, limits=limits, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > limits.max_container_items:
            raise ProtocolViolation("container_too_large", f"{path} contains too many array items")
        for index, item in enumerate(value):
            _validate_json_value(item, limits=limits, path=f"{path}[{index}]", depth=depth + 1)
        return
    raise ProtocolViolation(
        "non_json_value", f"{path} contains unsupported value type {type(value).__name__}"
    )


def _reject_private_runtime_keys(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _PRIVATE_RUNTIME_KEYS:
                raise ProtocolViolation(
                    "private_evaluation_data_rejected",
                    f"{path}.{key} is reserved for framework-private evaluation data",
                )
            _reject_private_runtime_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_runtime_keys(item, path=f"{path}[{index}]")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")

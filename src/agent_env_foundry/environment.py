"""Canonical environment contract and release loader (S1 Slice 1).

Transport-neutral surface every generated environment package implements:

- ``ToolSpec {name, description, input_schema, output_schema}``;
- uniform ``ToolObservation {ok, data, error}`` with exactly two valid variants;
- the ``Environment`` protocol ``reset/tools/invoke/close``;
- a runtime wrapper that validates reset starts against the release's
  ``start_schema``, every reset result against ``reset_observation_schema``,
  the tool catalog (unique names, complete self-contained Draft 2020-12
  schemas, object-root inputs) and every domain observation before it reaches
  the caller;
- ``load_environment``: standard ``module:factory`` import with a
  caller-owned instance directory (loading never implies reset).

Reserved ``contract.unknown_tool`` / ``contract.invalid_arguments``
observations are produced by the wrapper before any domain dispatch; the
``contract.*`` namespace is framework-owned and domain code may never emit it.
There is deliberately no MCP, HTTP, RPC, call-ID, Task or Registry surface
here — adapters own any transport or correlation concerns.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict, cast, runtime_checkable

from agent_env_foundry.errors import EnvironmentContractError, EnvironmentRuntimeError
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import ValidatedReleaseContract, verify_release
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_instance,
    validate_schema_document,
)

__all__ = [
    "CONTRACT_ERROR_PREFIX",
    "CONTRACT_INVALID_ARGUMENTS",
    "CONTRACT_UNKNOWN_TOOL",
    "Environment",
    "JSONObject",
    "JSONValue",
    "ToolError",
    "ToolObservation",
    "ToolSpec",
    "ValidatedEnvironment",
    "failure_observation",
    "invalid_arguments_observation",
    "is_contract_observation",
    "load_environment",
    "success_observation",
    "unknown_tool_observation",
    "validate_observation",
    "validate_tool_catalog",
]

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

CONTRACT_ERROR_PREFIX = "contract."
CONTRACT_UNKNOWN_TOOL = "contract.unknown_tool"
CONTRACT_INVALID_ARGUMENTS = "contract.invalid_arguments"

_TOOL_SPEC_KEYS = frozenset({"name", "description", "input_schema", "output_schema"})
_TOOL_ERROR_KEYS = frozenset({"code", "message", "details"})


class ToolSpec(TypedDict):
    name: str
    description: str
    input_schema: JSONObject
    output_schema: JSONObject


class ToolError(TypedDict):
    code: str
    message: str
    details: NotRequired[JSONValue]


class ToolObservation(TypedDict):
    ok: bool
    data: JSONValue | None
    error: ToolError | None


@runtime_checkable
class Environment(Protocol):
    def reset(self, start: JSONObject | None = None) -> JSONValue: ...
    def tools(self) -> tuple[ToolSpec, ...]: ...
    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation: ...
    def close(self) -> None: ...


# ----------------------------------------------------------- observation helpers


def success_observation(data: JSONValue) -> ToolObservation:
    return {"ok": True, "data": data, "error": None}


def failure_observation(
    code: str, message: str, details: JSONValue | None = None
) -> ToolObservation:
    error: ToolError = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"ok": False, "data": None, "error": error}


def unknown_tool_observation(tool_name: str) -> ToolObservation:
    return failure_observation(
        CONTRACT_UNKNOWN_TOOL,
        f"unknown tool {tool_name!r}",
        {"tool": tool_name},
    )


def invalid_arguments_observation(message: str, *, tool_name: str | None = None) -> ToolObservation:
    details: JSONValue | None = {"tool": tool_name} if tool_name is not None else None
    return failure_observation(CONTRACT_INVALID_ARGUMENTS, message, details)


def is_contract_observation(observation: ToolObservation) -> bool:
    """True for reserved invalid-action feedback; never business-refusal evidence."""
    error = observation.get("error")
    if observation.get("ok") or not isinstance(error, dict):
        return False
    code = error.get("code")
    return isinstance(code, str) and code.startswith(CONTRACT_ERROR_PREFIX)


# ----------------------------------------------------------------- validation


def validate_tool_catalog(specs: Any, *, role: str = "tools()") -> dict[str, ToolSpec]:
    """Validate the complete tool catalog and index it by unique tool name."""
    if not isinstance(specs, tuple):
        raise EnvironmentRuntimeError(
            f"{role} must return a tuple of ToolSpec, got {type(specs).__name__}"
        )
    index: dict[str, ToolSpec] = {}
    for position, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise EnvironmentRuntimeError(
                f"{role} entry {position} must be a ToolSpec object, got {type(spec).__name__}"
            )
        keys = set(spec)
        if keys != _TOOL_SPEC_KEYS:
            raise EnvironmentRuntimeError(
                f"{role} entry {position} must have exactly {sorted(_TOOL_SPEC_KEYS)}, "
                f"got {sorted(keys)}"
            )
        name = spec["name"]
        if not isinstance(name, str) or not name:
            raise EnvironmentRuntimeError(f"{role} entry {position} has invalid tool name {name!r}")
        if not isinstance(spec["description"], str):
            raise EnvironmentRuntimeError(
                f"{role} entry {position} ({name!r}) description must be a string"
            )
        try:
            require_object_root(spec["input_schema"], role=f"tool {name!r} input_schema")
            validate_schema_document(spec["output_schema"], role=f"tool {name!r} output_schema")
        except SchemaError as exc:
            raise EnvironmentRuntimeError(f"{role} entry {position} is invalid: {exc}") from exc
        if name in index:
            raise EnvironmentRuntimeError(f"{role} declares duplicate tool name {name!r}")
        index[name] = cast(ToolSpec, spec)
    return index


def validate_observation(
    observation: Any, spec: ToolSpec | None = None, *, role: str = "invoke()"
) -> None:
    """Validate an observation returned by domain code against the exact variants.

    Only the two documented variants are valid; anything else is a corrupt
    result. Reserved ``contract.*`` codes emitted by domain code are rejected
    because the namespace is framework-owned.
    """
    if not isinstance(observation, dict):
        raise EnvironmentRuntimeError(
            f"{role} returned {type(observation).__name__}, expected a ToolObservation object"
        )
    keys = set(observation)
    if keys != {"ok", "data", "error"}:
        raise EnvironmentRuntimeError(
            f"{role} returned keys {sorted(keys)}; a ToolObservation has exactly "
            "['data', 'error', 'ok']"
        )
    ok = observation["ok"]
    if not isinstance(ok, bool):
        raise EnvironmentRuntimeError(f"{role} returned non-boolean ok: {ok!r}")
    data = observation["data"]
    error = observation["error"]
    if ok:
        if error is not None:
            raise EnvironmentRuntimeError(
                f"{role} returned the contradictory variant ok=true with error={error!r}"
            )
        if not is_json_value(data):
            raise EnvironmentRuntimeError(
                f"{role} returned success data that is not a JSON value: {data!r}"
            )
        if spec is not None:
            try:
                validate_instance(data, spec["output_schema"], role=f"tool {spec['name']!r} data")
            except SchemaError as exc:
                raise EnvironmentRuntimeError(
                    f"{role} success data violates the declared output schema: {exc}"
                ) from exc
    else:
        if data is not None:
            raise EnvironmentRuntimeError(
                f"{role} returned the contradictory variant ok=false with data={data!r}"
            )
        _validate_tool_error(error, role=role)


def _validate_tool_error(error: Any, *, role: str) -> None:
    if not isinstance(error, dict):
        raise EnvironmentRuntimeError(f"{role} returned ok=false without a tool error object")
    keys = set(error)
    if not keys <= _TOOL_ERROR_KEYS or "code" not in keys or "message" not in keys:
        raise EnvironmentRuntimeError(
            f"{role} returned a tool error with keys {sorted(keys)}; expected "
            "['code', 'message'] with optional 'details'"
        )
    code = error["code"]
    if not isinstance(code, str) or not code:
        raise EnvironmentRuntimeError(f"{role} returned a tool error with invalid code {code!r}")
    if code.startswith(CONTRACT_ERROR_PREFIX):
        raise EnvironmentRuntimeError(
            f"{role} emitted reserved {CONTRACT_ERROR_PREFIX}* code {code!r}; the "
            "contract namespace is framework-owned and cannot carry business refusals"
        )
    if not isinstance(error["message"], str):
        raise EnvironmentRuntimeError(f"{role} returned a tool error with non-string message")
    if "details" in error and not is_json_value(error["details"]):
        raise EnvironmentRuntimeError(
            f"{role} returned tool error details that are not a JSON value"
        )


# ------------------------------------------------------------------- wrapper


class ValidatedEnvironment:
    """Runtime wrapper enforcing the release contract around an Environment."""

    def __init__(
        self,
        environment: Environment,
        *,
        start_schema: JSONObject | None,
        reset_observation_schema: JSONObject,
    ) -> None:
        self._environment = environment
        self._start_schema = start_schema
        self._reset_observation_schema = reset_observation_schema
        # Fail fast on a broken catalog before any reset can change state.
        self._catalog()

    def _catalog(self) -> dict[str, ToolSpec]:
        try:
            specs = self._environment.tools()
        except Exception as exc:
            raise EnvironmentRuntimeError(f"tools() failed: {exc}") from exc
        return validate_tool_catalog(specs)

    def reset(self, start: JSONObject | None = None) -> JSONValue:
        if start is not None:
            if not is_json_object(start):
                raise EnvironmentContractError(
                    f"reset start must be a JSON object or None, got {type(start).__name__}"
                )
            if self._start_schema is not None:
                try:
                    validate_instance(start, self._start_schema, role="reset start")
                except SchemaError as exc:
                    raise EnvironmentContractError(f"invalid reset start: {exc}") from exc
        try:
            observation = self._environment.reset(start)
        except Exception as exc:
            raise EnvironmentRuntimeError(f"reset failed: {exc}") from exc
        if not is_json_value(observation):
            raise EnvironmentRuntimeError(
                f"reset returned a value that is not JSON: {observation!r}"
            )
        try:
            validate_instance(observation, self._reset_observation_schema, role="reset observation")
        except SchemaError as exc:
            raise EnvironmentRuntimeError(
                f"reset observation violates the published reset_observation_schema: {exc}"
            ) from exc
        return observation

    def tools(self) -> tuple[ToolSpec, ...]:
        return tuple(self._catalog().values())

    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation:
        if not isinstance(tool_name, str):
            return invalid_arguments_observation(
                f"tool_name must be a string, got {type(tool_name).__name__}"
            )
        if not is_json_object(arguments):
            return invalid_arguments_observation(
                f"arguments must be a JSON object, got {type(arguments).__name__}"
            )
        spec = self._catalog().get(tool_name)
        if spec is None:
            return unknown_tool_observation(tool_name)
        try:
            validate_instance(arguments, spec["input_schema"], role=f"tool {tool_name!r} arguments")
        except SchemaError as exc:
            return invalid_arguments_observation(str(exc), tool_name=tool_name)
        try:
            observation = self._environment.invoke(tool_name, arguments)
        except Exception as exc:
            raise EnvironmentRuntimeError(f"invoke of tool {tool_name!r} failed: {exc}") from exc
        validate_observation(observation, spec, role=f"invoke of tool {tool_name!r}")
        return observation

    def close(self) -> None:
        try:
            self._environment.close()
        except Exception as exc:
            raise EnvironmentRuntimeError(f"close failed: {exc}") from exc


# -------------------------------------------------------------------- loading


def load_environment(
    release_path: str | Path, instance_directory: str | Path
) -> ValidatedEnvironment:
    """Load a release into a caller-owned instance directory.

    The instance directory is created if absent and handed to the release's
    standard ``module:factory`` entry point; loading implies no reset and never
    deletes committed state. Caller adapters own any transport concerns.
    """
    verified: ValidatedReleaseContract = verify_release(Path(release_path))
    module_name, _, attribute = verified.descriptor.environment_factory.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EnvironmentContractError(
            f"cannot import environment factory module {module_name!r}: {exc}"
        ) from exc
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise EnvironmentContractError(
            f"environment factory {verified.descriptor.environment_factory!r} is not callable"
        )
    instance = Path(instance_directory)
    instance.mkdir(parents=True, exist_ok=True)
    environment = factory(instance)
    for method in ("reset", "tools", "invoke", "close"):
        if not callable(getattr(environment, method, None)):
            raise EnvironmentContractError(
                f"environment factory {verified.descriptor.environment_factory!r} returned "
                f"an object missing the canonical {method} method"
            )
    return ValidatedEnvironment(
        environment,
        start_schema=verified.start_schema,
        reset_observation_schema=verified.reset_observation_schema,
    )

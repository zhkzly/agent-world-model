"""ValidatedEnvironment wrapper behavior for reset/tools/invoke/close (Slice 1).

All environments are mechanical fixtures; none is a domain environment (PRD F8).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fx_contract_ok import RESET_OBSERVATION_SCHEMA, START_SCHEMA, MechanicalEnvironment

from agent_env_foundry.environment import (
    CONTRACT_INVALID_ARGUMENTS,
    CONTRACT_UNKNOWN_TOOL,
    ValidatedEnvironment,
)
from agent_env_foundry.errors import EnvironmentContractError, EnvironmentRuntimeError

OK_SPEC: dict[str, Any] = {
    "name": "t",
    "description": "mechanical tool",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
}


class ScriptedEnvironment:
    """Inline mechanical environment with injectable behavior."""

    def __init__(
        self,
        *,
        tools_result: Any = None,
        reset_behavior: Callable[[Any], Any] | None = None,
        invoke_behavior: Callable[[str, dict[str, Any]], Any] | None = None,
        close_behavior: Callable[[], None] | None = None,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._tools_result = (OK_SPEC,) if tools_result is None else tools_result
        self._reset_behavior = reset_behavior or _valid_reset
        self._invoke_behavior = invoke_behavior or (
            lambda name, arguments: {"ok": True, "data": {}, "error": None}
        )
        self._close_behavior = close_behavior

    def reset(self, start: dict[str, Any] | None = None) -> Any:
        self.calls.append(("reset", start))
        return self._reset_behavior(start)

    def tools(self) -> Any:
        self.calls.append(("tools", None))
        return self._tools_result

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append(("invoke", tool_name, arguments))
        return self._invoke_behavior(tool_name, arguments)

    def close(self) -> None:
        self.calls.append(("close", None))
        if self._close_behavior is not None:
            self._close_behavior()


def _valid_reset(start: Any) -> dict[str, Any]:
    return {
        "kind": "mechanical",
        "token": 1,
        "started": start is not None,
        "seed": start.get("seed") if start is not None else None,
    }


def _raise_reset(start: Any) -> dict[str, Any]:
    raise RuntimeError("reset exploded")


def make_wrapper(
    environment: Any,
    *,
    start_schema: Any = START_SCHEMA,
    reset_observation_schema: Any = RESET_OBSERVATION_SCHEMA,
) -> ValidatedEnvironment:
    return ValidatedEnvironment(
        environment,
        start_schema=start_schema,
        reset_observation_schema=reset_observation_schema,
    )


def dispatched(environment: Any) -> list[tuple[Any, ...]]:
    return [call for call in environment.calls if call[0] == "invoke"]


# ---------------------------------------------------------------------- reset


def test_reset_returns_validated_initial_observation() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.reset()
    assert observation["kind"] == "mechanical"
    assert observation["token"] == 1
    assert observation["started"] is False

    started = env.reset({"seed": 4})
    assert started["started"] is True
    assert started["seed"] == 4


@pytest.mark.parametrize("bad_start", [{"seed": -1}, {"unexpected": 1}, ["x"], 5, "x", True])
def test_invalid_reset_start_is_a_contract_error_before_state_change(bad_start: Any) -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    with pytest.raises(EnvironmentContractError):
        env.reset(bad_start)
    # Eager catalog validation may have called tools(); reset never ran.
    assert [call[0] for call in mechanical.calls if call[0] != "tools"] == []


def test_reset_without_start_schema_accepts_object_starts() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical, start_schema=None)
    assert env.reset()["kind"] == "mechanical"
    assert env.reset({"anything": [1, 2]})["started"] is True


def _schema_violating_reset(start: Any) -> dict[str, Any]:
    return {"kind": "wrong_shape"}


def _non_json_reset(start: Any) -> Any:
    return object()


@pytest.mark.parametrize(
    "reset_behavior",
    [_schema_violating_reset, _non_json_reset, _raise_reset],
)
def test_bad_reset_results_are_runtime_errors(reset_behavior: Callable[[Any], Any]) -> None:
    env = make_wrapper(ScriptedEnvironment(reset_behavior=reset_behavior))
    with pytest.raises(EnvironmentRuntimeError):
        env.reset()


def test_reset_runtime_error_preserves_cause() -> None:
    env = make_wrapper(ScriptedEnvironment(reset_behavior=_raise_reset))
    with pytest.raises(EnvironmentRuntimeError) as excinfo:
        env.reset()
    assert isinstance(excinfo.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------- tools


def test_tools_returns_catalog() -> None:
    env = make_wrapper(MechanicalEnvironment(None))
    specs = env.tools()
    assert isinstance(specs, tuple)
    assert [spec["name"] for spec in specs] == ["next_value", "echo", "refuse"]


def test_tools_runtime_failure_is_wrapped() -> None:
    class Broken:
        calls: list[tuple[Any, ...]] = []

        def reset(self, start: Any = None) -> Any:
            return {}

        def tools(self) -> Any:
            raise RuntimeError("catalog unavailable")

        def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any:
            raise AssertionError("not reached")

        def close(self) -> None:
            return None

    with pytest.raises(EnvironmentRuntimeError):
        make_wrapper(Broken()).tools()


# --------------------------------------------------------------------- invoke


def test_valid_invoke_returns_domain_observation() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.invoke("next_value", {})
    assert observation == {"ok": True, "data": {"value": 1}, "error": None}
    assert ("invoke", "next_value", {}) in mechanical.calls


def test_successful_data_is_machine_addressable_and_chainable() -> None:
    env = make_wrapper(MechanicalEnvironment(None))
    first = env.invoke("next_value", {})
    second = env.invoke("echo", {"value": first["data"]["value"]})
    assert second["data"]["value"] == first["data"]["value"]


def test_business_refusal_is_a_valid_observation() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.invoke("refuse", {})
    assert observation["ok"] is False
    assert observation["data"] is None
    assert observation["error"]["code"] == "mechanical_refusal"
    assert ("invoke", "refuse", {}) in mechanical.calls


def test_unknown_tool_returns_contract_observation_without_dispatch() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.invoke("does_not_exist", {})
    assert observation["ok"] is False
    assert observation["data"] is None
    assert observation["error"]["code"] == CONTRACT_UNKNOWN_TOOL
    assert "does_not_exist" in observation["error"]["message"]
    assert dispatched(mechanical) == []


@pytest.mark.parametrize(
    "arguments",
    [{"unexpected": 1}, [1, 2], "x", 5, None, True],
)
def test_invalid_arguments_return_contract_observation_without_dispatch(
    arguments: Any,
) -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.invoke("next_value", arguments)
    assert observation["ok"] is False
    assert observation["error"]["code"] == CONTRACT_INVALID_ARGUMENTS
    assert dispatched(mechanical) == []


def test_non_string_tool_name_is_invalid_arguments() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    observation = env.invoke(123, {})  # type: ignore[arg-type]
    assert observation["error"]["code"] == CONTRACT_INVALID_ARGUMENTS
    assert dispatched(mechanical) == []


def _raise_invoke(name: str, arguments: dict[str, Any]) -> Any:
    raise TimeoutError("domain timeout")


INVOKE_FAULTS: dict[str, Callable[[str, dict[str, Any]], Any]] = {
    "ok_with_error": lambda n, a: {"ok": True, "data": {}, "error": {"code": "x", "message": "m"}},
    "ok_false_with_data": lambda n, a: {
        "ok": False,
        "data": {"v": 1},
        "error": {"code": "x", "message": "m"},
    },
    "ok_false_without_error": lambda n, a: {"ok": False, "data": None, "error": None},
    "extra_call_id_key": lambda n, a: {"ok": True, "data": {}, "error": None, "call_id": "abc"},
    "contract_squat": lambda n, a: {
        "ok": False,
        "data": None,
        "error": {"code": "contract.sold_out", "message": "domain refusal"},
    },
    "bad_output_data": lambda n, a: {"ok": True, "data": 5, "error": None},
    "non_json_data": lambda n, a: {"ok": True, "data": object(), "error": None},
    "not_a_dict": lambda n, a: None,
    "raising": _raise_invoke,
}


@pytest.mark.parametrize("fault", sorted(INVOKE_FAULTS))
def test_faulty_domain_results_are_runtime_errors(fault: str) -> None:
    env = make_wrapper(ScriptedEnvironment(invoke_behavior=INVOKE_FAULTS[fault]))
    with pytest.raises(EnvironmentRuntimeError):
        env.invoke("t", {})


def test_invoke_runtime_error_preserves_cause() -> None:
    env = make_wrapper(ScriptedEnvironment(invoke_behavior=_raise_invoke))
    with pytest.raises(EnvironmentRuntimeError) as excinfo:
        env.invoke("t", {})
    assert isinstance(excinfo.value.__cause__, TimeoutError)


# ---------------------------------------------------------------------- close


def test_close_passthrough() -> None:
    mechanical = MechanicalEnvironment(None)
    env = make_wrapper(mechanical)
    env.close()
    assert ("close", None) in mechanical.calls


def _raise_close() -> None:
    raise RuntimeError("close failed")


def test_close_failure_is_runtime_error() -> None:
    env = make_wrapper(ScriptedEnvironment(close_behavior=_raise_close))
    with pytest.raises(EnvironmentRuntimeError):
        env.close()


# ------------------------------------------------------------- public surface


def test_wrapper_surface_is_exactly_the_canonical_api() -> None:
    env = make_wrapper(MechanicalEnvironment(None))
    callables = {
        name for name in dir(env) if not name.startswith("_") and callable(getattr(env, name))
    }
    assert callables == {"reset", "tools", "invoke", "close"}
    # No correlation-ID / transport surface exists to misuse.
    assert not hasattr(env, "call_id")
    assert not hasattr(env, "tool_call_id")

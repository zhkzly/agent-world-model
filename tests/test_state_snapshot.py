from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_env_foundry.physical_runtime import (
    PreparationExecutionError,
    StateSnapshotProxy,
)


class _Transport:
    def __init__(
        self,
        value: Any,
        *,
        mutate: bool = False,
    ) -> None:
        self.value = value
        self.mutate = mutate
        self.closed = False

    def call(self, operation: str, arguments: dict[str, Any]) -> Any:
        assert operation == "read"
        instance = Path(arguments["instance_directory"])
        if self.mutate:
            (instance / "reader-mutated.txt").write_text("forbidden")
        return self.value

    def close(self, *, operation: str | None = None) -> None:
        assert operation == "close"
        self.closed = True


class _SequenceTransport(_Transport):
    def __init__(self, values: list[Any]) -> None:
        super().__init__(None)
        self.values = values

    def call(self, operation: str, arguments: dict[str, Any]) -> Any:
        assert operation == "read"
        assert Path(arguments["instance_directory"]).is_dir()
        return self.values.pop(0)


def test_state_snapshot_is_schema_valid_deterministic_and_read_only(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    (instance / "state.db").write_text("persistent bytes")
    events = []
    transport = _Transport({"count": 3})
    proxy = StateSnapshotProxy(
        transport,
        state_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        events=events,
    )

    first = proxy.read(instance)
    second = proxy.read(instance)
    proxy.close()

    assert first == second == {"count": 3}
    assert len(events) == 2 and all(event.unchanged for event in events)
    assert transport.closed


def test_state_snapshot_rejects_schema_drift(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    proxy = StateSnapshotProxy(
        _Transport({"count": "three"}),
        state_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        events=[],
    )

    with pytest.raises(PreparationExecutionError) as caught:
        proxy.read(instance)

    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "state_snapshot_schema"


def test_state_snapshot_rejects_reader_mutation_even_with_valid_value(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    events = []
    proxy = StateSnapshotProxy(
        _Transport({"count": 1}, mutate=True),
        state_schema={"type": "object"},
        events=events,
    )

    with pytest.raises(PreparationExecutionError) as caught:
        proxy.read(instance)

    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "state_snapshot_mutation"
    assert len(events) == 1 and not events[0].unchanged


def test_state_snapshot_rejects_different_values_for_unchanged_native_bytes(
    tmp_path: Path,
) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    proxy = StateSnapshotProxy(
        _SequenceTransport([{"count": 1}, {"count": 2}]),
        state_schema={"type": "object"},
        events=[],
    )

    assert proxy.read(instance) == {"count": 1}
    with pytest.raises(PreparationExecutionError) as caught:
        proxy.read(instance)

    assert caught.value.code == "state_snapshot_nondeterministic"

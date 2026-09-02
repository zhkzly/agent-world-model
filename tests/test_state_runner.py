from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_env_foundry._state_runner import _dispatch, _request


def test_state_runner_dispatches_only_protected_read_and_close(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    observed: list[Path] = []

    def reader(path: Path) -> dict[str, int]:
        observed.append(path)
        return {"count": 4}

    assert _dispatch(reader, "read", {"instance_directory": str(instance)}) == {"count": 4}
    assert observed == [instance]
    assert _dispatch(reader, "close", {}) is None
    with pytest.raises(ValueError, match="unknown state operation"):
        _dispatch(reader, "capabilities", {})


def test_state_runner_request_is_exact_and_sequenced() -> None:
    request = {"seq": 1, "op": "read", "args": {"instance_directory": "/instance"}}
    assert _request(json.dumps(request)) == (
        1,
        "read",
        {"instance_directory": "/instance"},
    )

    for invalid in (
        {**request, "extra": True},
        {**request, "seq": 0},
        {**request, "op": 7},
        {**request, "args": []},
    ):
        with pytest.raises(ValueError):
            _request(json.dumps(invalid))

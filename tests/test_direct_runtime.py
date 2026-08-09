from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_world.contracts import PublicStep
from agent_world.runtime import integrate, judge


def _candidate(root: Path, *, valid_protocol: bool = True, result: object | None = None) -> None:
    operations = '["handshake","reset","invoke","close"]' if valid_protocol else '["reset"]'
    invoke_response = json.dumps(
        {"status": "ok", "result": {"value": "ok"} if result is None else result}
    )
    (root / "runtime.py").write_text(
        f"""import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    operation = request.get("op")
    if operation == "handshake":
        response = {{"operations": {operations}}}
    elif operation == "reset":
        response = {{"status": "ok"}}
    elif operation == "invoke":
        print({invoke_response!r}, flush=True)
        continue
    elif operation == "close":
        response = {{"status": "ok"}}
        print(json.dumps(response), flush=True)
        break
    else:
        response = {{"status": "error"}}
    print(json.dumps(response), flush=True)
""",
        encoding="utf-8",
    )


def test_independent_judge_repeats_framework_protocol_checks(tmp_path: Path) -> None:
    _candidate(tmp_path, result={"value": "ok", "extra": "permitted"})
    step = PublicStep(tool="lookup", arguments={}, expected_result={"value": "ok"})

    assert integrate(tmp_path, step) == {"status": "passed", "code": "ok"}
    assert all(gate["status"] == "passed" for gate in judge(tmp_path, step))


@pytest.mark.parametrize(
    ("step", "result"),
    [
        (PublicStep(tool="lookup", arguments={}, expected_result={"value": True}), {"value": 1}),
        (PublicStep(tool="lookup", arguments={}, expected_result={"value": 1}), {"value": 1.0}),
        (
            PublicStep(tool="lookup", arguments={}, expected_result={"value": 1.0}),
            {"value": float("nan")},
        ),
    ],
    ids=("boolean-is-not-integer", "integer-is-not-float", "nonfinite-float"),
)
def test_property_mismatch_blocks_integration_and_core_property(
    tmp_path: Path, step: PublicStep, result: object
) -> None:
    _candidate(tmp_path, result=result)

    assert integrate(tmp_path, step) == {
        "status": "failed",
        "code": "candidate_property_mismatch",
    }
    gates = {gate["gate_id"]: gate for gate in judge(tmp_path, step)}

    assert gates["core_property"] == {
        "gate_id": "core_property",
        "status": "failed",
        "code": "candidate_property_mismatch",
    }
    assert all(
        gate["status"] == "passed" for gate_id, gate in gates.items() if gate_id != "core_property"
    )


def test_protocol_mismatch_is_a_release_blocking_gate(tmp_path: Path) -> None:
    _candidate(tmp_path, valid_protocol=False)
    step = PublicStep(tool="lookup", arguments={}, expected_result={"value": "ok"})

    gates = {gate["gate_id"]: gate for gate in judge(tmp_path, step)}

    assert gates["protocol"] == {
        "gate_id": "protocol",
        "status": "failed",
        "code": "candidate_protocol_mismatch",
    }

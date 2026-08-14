from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_world.candidate import CandidateError, CandidateExecutor, _model_rejection
from agent_world.contracts import SafeFailure
from agent_world.graph import NodeExecutionError
from agent_world.invocation import InvocationError, InvocationResult


class _FlakyAgent:
    def __init__(self, failure_code: str, status: str = "rejected", retryable: bool = False) -> None:
        self.failure_code = failure_code
        self.status = status
        self.retryable = retryable
        self.calls = 0
        self.instructions: list[str] = []

    def invoke_json(self, **kwargs: object) -> InvocationResult:
        self.calls += 1
        self.instructions.append(str(kwargs["instruction"]))
        raise InvocationError(
            SafeFailure(self.failure_code, self.status, self.retryable)  # type: ignore[arg-type]
        )


class _ThenValidAgent(_FlakyAgent):
    def invoke_json(self, **kwargs: object) -> InvocationResult:
        self.calls += 1
        self.instructions.append(str(kwargs["instruction"]))
        if self.calls == 1:
            raise InvocationError(
                SafeFailure(self.failure_code, self.status, self.retryable)  # type: ignore[arg-type]
            )
        return InvocationResult({"steps": []}, "agent-test", None, "sha256:" + "c" * 64)


def _executor(agent: object) -> CandidateExecutor:
    settings = SimpleNamespace(trusted_wheel_store=None)
    return CandidateExecutor(settings, agent)  # type: ignore[arg-type]


def test_agent_response_not_json_carries_correction_packet(tmp_path: Path) -> None:
    agent = _FlakyAgent("agent_response_not_json")
    executor = _executor(agent)
    with pytest.raises(NodeExecutionError) as raised:
        executor._agent_json("build_plan", "engineer-build-planning", tmp_path, "instruction")
    assert raised.value.correction is not None
    assert raised.value.correction.code == "agent_response_not_json"
    assert "one JSON object" in raised.value.correction.violated_condition


def test_correction_reinjects_and_second_attempt_succeeds(tmp_path: Path) -> None:
    agent = _ThenValidAgent("agent_response_not_json")
    executor = _executor(agent)
    with pytest.raises(NodeExecutionError) as raised:
        executor._agent_json("build_plan", "engineer-build-planning", tmp_path, "instruction")
    proposal = executor._agent_json(
        "build_plan",
        "engineer-build-planning",
        tmp_path,
        "instruction",
        correction=raised.value.correction,
    )
    assert agent.calls == 2
    assert proposal.value == {"steps": []}
    assert "Authorized correction packet" in agent.instructions[1]


def test_other_invocation_codes_stay_non_correctable(tmp_path: Path) -> None:
    agent = _FlakyAgent("agent_timeout", "error", True)
    executor = _executor(agent)
    with pytest.raises(CandidateError) as raised:
        executor._agent_json("build_plan", "engineer-build-planning", tmp_path, "instruction")
    assert raised.value.code == "agent_timeout"
    assert not hasattr(raised.value, "correction") or raised.value.correction is None


def test_model_rejection_shape() -> None:
    error = _model_rejection("agent_response_invalid", "$", "condition", "object")
    assert error.correction is not None
    assert error.correction.code == "agent_response_invalid"
    assert error.correction.path == "$"

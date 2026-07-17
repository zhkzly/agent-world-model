from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
from pydantic import JsonValue

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import Budget, PublicTask, RuntimeAction
from agent_world.contracts.reachability import (
    ParameterizedSolveStep,
    RecipeLiteral,
    RecipePointer,
)
from agent_world.invocation import (
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)
from agent_world.judge.reachability import (
    EpisodeStepResult,
    InteractiveChallengerStrategy,
    ReachabilityInputError,
    materialize_recipe_arguments,
    resolve_json_pointer,
    resolve_recipe_pointer,
)
from agent_world.judge.service import FindingOwner, GateStatus, _worse_reachability_route


def test_reachability_failure_reduction_keeps_status_and_owner_atomic() -> None:
    infrastructure_error: tuple[GateStatus, FindingOwner] = (
        "error",
        "judge_infrastructure",
    )
    candidate_failure: tuple[GateStatus, FindingOwner] = ("fail", "build")
    verifier_inconclusive: tuple[GateStatus, FindingOwner] = (
        "inconclusive",
        "verifier",
    )

    assert (
        _worse_reachability_route(infrastructure_error, candidate_failure) == infrastructure_error
    )
    assert _worse_reachability_route(verifier_inconclusive, candidate_failure) == candidate_failure


class _TwoStepEpisode:
    def __init__(self) -> None:
        self.steps = 0

    @property
    def public_task(self) -> PublicTask:
        return PublicTask(
            seed=7,
            task_type="increase",
            actor="user",
            public_instruction="Increase twice.",
            public_goal={"target": 2},
            difficulty={"scale": "small"},
        )

    @property
    def reset_observation(self) -> JsonValue:
        return {"counter": 0}

    @property
    def tool_schemas(self) -> dict[str, dict[str, JsonValue]]:
        return {
            "counter.increment": {
                "type": "object",
                "properties": {"amount": {"type": "integer"}},
                "required": ["amount"],
                "additionalProperties": False,
            }
        }

    async def execute(self, action: RuntimeAction) -> EpisodeStepResult:
        assert action.tool_id == "counter.increment"
        self.steps += 1
        succeeded = self.steps == 2
        return EpisodeStepResult(
            observation={"counter": self.steps},
            tool_result={"value": self.steps},
            reward=1.0 if succeeded else 0.0,
            terminated=succeeded,
            succeeded=succeeded,
            failed=False,
        )


class _BudgetProbeBackend:
    """Deterministic backend probe that records the real resolved hard caps."""

    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        session = InvocationSession(
            thread_id="thread:budget-probe",
            lineage_id=request.profile.lineage_id,
            workspace=request.profile.workspace,
            profile_hash=request.profile.profile_hash,
            codex_config_sha256=request.profile.codex_config_sha256,
        )
        cap = request.profile.rollout_token_limit
        assert cap is not None
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=session,
            turn_id=f"turn:{len(self.requests)}",
            final_text=None,
            structured_output={
                "schema_version": "v2",
                "decision": "action",
                "action": {
                    "schema_version": "v2",
                    "tool_id": "counter.increment",
                    "arguments": {"amount": 1},
                    "idempotency_key": None,
                },
                "reason": None,
            },
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=cap)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


def test_episode_step_contract_contains_only_agent_visible_and_trusted_terminal_fields() -> None:
    assert {field.name for field in fields(EpisodeStepResult)} == {
        "observation",
        "tool_result",
        "reward",
        "terminated",
        "succeeded",
        "failed",
    }


def test_episode_step_requires_framework_consistent_terminal_flags() -> None:
    with pytest.raises(ValueError, match="must terminate"):
        EpisodeStepResult(
            observation={},
            tool_result={},
            reward=1.0,
            terminated=False,
            succeeded=True,
            failed=False,
        )

    with pytest.raises(ValueError, match="both succeed and fail"):
        EpisodeStepResult(
            observation={},
            tool_result={},
            reward=0.0,
            terminated=True,
            succeeded=True,
            failed=True,
        )


def test_strict_json_pointer_resolves_escaped_object_and_array_tokens() -> None:
    document: JsonValue = {"a/b": {"~key": [{"": "selected"}]}}

    assert resolve_json_pointer(document, "/a~1b/~0key/0/") == "selected"


def test_json_pointer_result_does_not_alias_public_input() -> None:
    document: JsonValue = {"goal": {"ids": ["one", "two"]}}

    resolved = resolve_json_pointer(document, "/goal/ids")
    assert isinstance(resolved, list)
    resolved.append("mutated")

    assert document == {"goal": {"ids": ["one", "two"]}}


@pytest.mark.parametrize(
    ("document", "pointer", "code"),
    [
        ({"value": 1}, "", "recipe_pointer_root_forbidden"),
        ({"value": 1}, "/", "recipe_pointer_root_forbidden"),
        ({"~2": 1}, "/~2", "recipe_pointer_invalid_escape"),
        ({"items": [1]}, "/items/01", "recipe_pointer_invalid_array_index"),
        ({"items": [1]}, "/items/-", "recipe_pointer_invalid_array_index"),
        ({"items": [1]}, "/items/1", "recipe_pointer_array_index_out_of_range"),
        ({"value": 1}, "/missing", "recipe_pointer_missing_key"),
        ({"value": 1}, "/value/child", "recipe_pointer_traverses_scalar"),
    ],
)
def test_strict_json_pointer_rejects_ambiguous_or_missing_paths(
    document: JsonValue,
    pointer: str,
    code: str,
) -> None:
    with pytest.raises(ReachabilityInputError) as captured:
        resolve_json_pointer(document, pointer)

    assert captured.value.code == code


def test_recipe_pointer_can_only_read_the_selected_public_envelope() -> None:
    previous = (
        EpisodeStepResult(
            observation={"visible": {"next": "obs-value"}},
            tool_result={"created": {"id": "result-value"}},
            reward=0.0,
            terminated=False,
            succeeded=False,
            failed=False,
        ),
    )

    assert (
        resolve_recipe_pointer(
            RecipePointer(source="public_goal", pointer="/target/id"),
            public_goal={"target": {"id": "goal-value"}},
            reset_observation={"selected": "reset-value"},
            previous_steps=previous,
        )
        == "goal-value"
    )
    assert (
        resolve_recipe_pointer(
            RecipePointer(source="reset_observation", pointer="/selected"),
            public_goal={"target": {"id": "goal-value"}},
            reset_observation={"selected": "reset-value"},
            previous_steps=previous,
        )
        == "reset-value"
    )
    assert (
        resolve_recipe_pointer(
            RecipePointer(
                source="previous_tool_result",
                pointer="/created/id",
                previous_step_index=0,
            ),
            public_goal={},
            reset_observation={},
            previous_steps=previous,
        )
        == "result-value"
    )
    assert (
        resolve_recipe_pointer(
            RecipePointer(
                source="previous_observation",
                pointer="/visible/next",
                previous_step_index=0,
            ),
            public_goal={},
            reset_observation={},
            previous_steps=previous,
        )
        == "obs-value"
    )


def test_recipe_rejects_unexecuted_previous_step_reference() -> None:
    pointer = RecipePointer(
        source="previous_tool_result",
        pointer="/id",
        previous_step_index=0,
    )

    with pytest.raises(ReachabilityInputError) as captured:
        resolve_recipe_pointer(
            pointer,
            public_goal={},
            reset_observation={},
            previous_steps=(),
        )

    assert captured.value.code == "recipe_previous_step_unavailable"


def test_recipe_argument_materialization_is_closed_and_copying() -> None:
    previous = (
        EpisodeStepResult(
            observation={"current": "open"},
            tool_result={"id": "generated-id"},
            reward=0.0,
            terminated=False,
            succeeded=False,
            failed=False,
        ),
    )
    literal: JsonValue = ["alpha", {"nested": True}]
    step = ParameterizedSolveStep(
        step_id="reserve",
        tool_id="inventory.reserve",
        arguments={
            "target": RecipePointer(source="public_goal", pointer="/target"),
            "warehouse": RecipePointer(source="reset_observation", pointer="/warehouse"),
            "reservation_id": RecipePointer(
                source="previous_tool_result",
                pointer="/id",
                previous_step_index=0,
            ),
            "constant": RecipeLiteral(value=literal),
        },
    )

    arguments = materialize_recipe_arguments(
        step,
        public_goal={"target": "sku-7"},
        reset_observation={"warehouse": "north"},
        previous_steps=previous,
    )

    assert arguments == {
        "target": "sku-7",
        "warehouse": "north",
        "reservation_id": "generated-id",
        "constant": literal,
    }
    constant = arguments["constant"]
    assert isinstance(constant, list)
    constant.append("changed")
    assert literal == ["alpha", {"nested": True}]


@pytest.mark.asyncio
async def test_interactive_solver_hard_caps_each_turn_without_breaking_session(
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text('{"tokens":{"access_token":"budget-probe-credential"}}')
    auth_file.chmod(0o600)
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(model="configured-model", chatgpt_auth_file=auth_file),
        source_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    backend = _BudgetProbeBackend()
    strategy = InteractiveChallengerStrategy(
        invocation_backend=backend,
        profile_provider=profiles,
    )

    outcome = await strategy.solve(
        driver=_TwoStepEpisode(),
        lineage_id="reachability-budget-probe",
        workspace=tmp_path / "solver-workspace",
        budget=Budget(llm_tokens=10, agent_turns=2, tool_calls=2),
        required_tool_ids=("counter.increment",),
        minimum_tool_calls=2,
        maximum_agent_turns=2,
        maximum_steps=2,
    )

    assert outcome.certified
    assert outcome.usage.llm_tokens == 10
    assert [request.profile.rollout_token_limit for request in backend.requests] == [5, 5]
    assert backend.requests[0].session is None
    assert backend.requests[1].session is not None
    assert backend.requests[1].session.profile_hash == backend.requests[1].profile.profile_hash

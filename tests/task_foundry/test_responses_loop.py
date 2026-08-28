from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai.types.responses import FunctionToolParam, ResponseFunctionToolCall, ResponseInputParam

from agent_task_foundry.compiler import TaskCheckResult
from agent_task_foundry.models import (
    AtomGoal,
    CheckerArtifact,
    InstructionAudit,
    ResolvedSelector,
    SelectorPredicate,
    SelectorSpec,
    StartRecipe,
    TaskBlueprint,
    TaskDefinition,
)
from agent_task_foundry.runner import (
    _ResponseTurn,
    _responses_tool,
    _run_responses_policy_loop,
)

OBJECT = {"type": "object", "additionalProperties": True}


@dataclass
class Actor:
    state: dict[str, Any]

    def reset(self, start: dict[str, Any] | None = None) -> dict[str, Any]:
        self.state.clear()
        return {"actor": "user"}

    def tools(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "name": "finish_item",
                "description": "finish an item",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "output_schema": OBJECT,
            },
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.state[arguments["name"]] = True
        return {
            "ok": True,
            "data": {"confirmation": f"ok-{arguments['name']}"},
            "error": None,
        }

    def close(self) -> None:
        return


class Checker:
    def evaluate(self, before, after, trace, answer) -> TaskCheckResult:
        if after.get("alpha") is True and answer == {"confirmation": "ok-alpha"}:
            return TaskCheckResult("satisfied", (), {"confirmation": "ok-alpha"})
        return TaskCheckResult("failed", ("not_finished",), {})


def definition() -> TaskDefinition:
    selector = SelectorSpec(
        "target",
        "finish",
        (SelectorPredicate("name", "eq", "alpha"),),
    )
    blueprint = TaskBlueprint(
        "release",
        "semantics",
        StartRecipe("release", "case", None),
        (selector,),
        AtomGoal("finish", "target"),
    )
    artifact = CheckerArtifact(
        blueprint.blueprint_id,
        (ResolvedSelector("target", ("alpha",)),),
        "checker-digest",
    )
    return TaskDefinition(
        blueprint,
        artifact,
        "finish the item whose name is alpha.",
        OBJECT,
        {"actor": "user"},
        InstructionAudit(True),
    )


def test_function_tool_uses_official_typed_shape() -> None:
    tool: FunctionToolParam = _responses_tool(Actor({}).tools()[0])
    assert tool == {
        "type": "function",
        "name": "finish_item",
        "description": "finish an item",
        "parameters": Actor({}).tools()[0]["input_schema"],
        "strict": True,
    }


def test_typed_responses_loop_round_trips_call_and_output_items() -> None:
    actor = Actor({})
    seen_histories: list[ResponseInputParam] = []

    def create_turn(
        history: ResponseInputParam,
        tools: list[FunctionToolParam],
    ) -> _ResponseTurn:
        seen_histories.append(list(history))
        assert tools[0]["name"] == "finish_item"
        if len(seen_histories) == 1:
            return _ResponseTurn(
                (
                    ResponseFunctionToolCall(
                        arguments='{"name":"alpha"}',
                        call_id="call-1",
                        name="finish_item",
                        type="function_call",
                    ),
                ),
                "",
            )
        return _ResponseTurn((), '{"confirmation":"ok-alpha"}')

    task = definition()
    run = _run_responses_policy_loop(
        actor=actor,
        definition=task,
        checker=Checker(),
        before_facts={},
        after_facts=lambda: actor.state,
        create_turn=create_turn,
        materialization_id="episode-1",
    )

    assert run.successful
    assert len(seen_histories) == 2
    continuation = seen_histories[1]
    assert any(item.get("type") == "function_call" for item in continuation)
    assert any(item.get("type") == "function_call_output" for item in continuation)
    assert run.trace[0].provenance.complete

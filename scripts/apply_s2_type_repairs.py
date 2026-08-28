"""Apply the reviewed S2 typing/semantic repairs exactly once.

This script is intentionally guarded by exact source anchors. It exits instead
of guessing when the branch has drifted.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new: str, *, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start anchor missing")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end anchor missing")
    return text[:start_index] + new + text[end_index:]


def patch_compiler() -> None:
    path = ROOT / "src/agent_task_foundry/compiler.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    ConditionSpec,\n    JSONObject,\n",
        "    ConditionSpec,\n    FacetSpec,\n    JSONObject,\n",
        label="compiler FacetSpec import",
    )
    text = replace_once(
        text,
        "from agent_task_foundry.models import (\n",
        "from agent_task_foundry.facets import (\n"
        "    FacetValueError,\n"
        "    compare_facet_values,\n"
        "    extreme_facet_value,\n"
        ")\n"
        "from agent_task_foundry.models import (\n",
        label="compiler facet helper import",
    )
    text = replace_once(
        text,
        "        if isinstance(goal, AllGoal):\n"
        "            return _combine(\n"
        "                [self._goal(child, before, after, trace, answer) for child in goal.children],\n"
        "                \"all\",\n"
        "            )\n"
        "        return self._if(goal, before, after, trace, answer)\n",
        "        if isinstance(goal, AllGoal):\n"
        "            return _combine(\n"
        "                [\n"
        "                    self._goal(child_goal, before, after, trace, answer)\n"
        "                    for child_goal in goal.children\n"
        "                ],\n"
        "                \"all\",\n"
        "            )\n"
        "        if isinstance(goal, IfGoal):\n"
        "            return self._if(goal, before, after, trace, answer)\n"
        "        raise CompilationError(f\"unsupported goal type {type(goal).__name__}\")\n",
        label="checker exhaustive goal dispatch",
    )
    rank_and_compare = '''def _rank(
    candidates: list[BindingCandidate],
    rank: RankSpec,
    facets: Mapping[str, FacetSpec],
) -> list[BindingCandidate]:
    facet = facets.get(rank.facet)
    if facet is None:
        raise CompilationError(f"unknown rank facet {rank.facet!r}")
    if rank.direction not in facet.allowed_operators:
        raise CompilationError(
            f"rank direction {rank.direction!r} is not allowed for facet {rank.facet!r}"
        )
    values = [candidate.facets.get(rank.facet) for candidate in candidates]
    try:
        target = extreme_facet_value(values, rank.direction)
    except FacetValueError as exc:
        raise CompilationError(f"invalid rank facet {rank.facet!r}: {exc}") from exc
    return [
        candidate
        for candidate in candidates
        if compare_facet_values(candidate.facets.get(rank.facet), "eq", target)
    ]


def _compare(left: JSONValue, operator: str, right: JSONValue) -> bool:
    try:
        return compare_facet_values(left, operator, right)
    except FacetValueError as exc:
        raise CompilationError(f"invalid facet comparison {operator!r}: {exc}") from exc


'''
    text = replace_between(
        text,
        "def _rank(\n",
        "def _validate_goal(\n",
        rank_and_compare,
        label="compiler rank and comparison",
    )
    validate_goal = '''def _validate_goal(
    goal: GoalProgram,
    selectors: Mapping[str, SelectorSpec],
    catalog: SemanticsCatalog,
) -> None:
    if isinstance(goal, AtomGoal):
        selector = _selector(goal.selector_id, selectors)
        capability = catalog.capability(goal.capability_id)
        if selector.capability_id != goal.capability_id:
            raise CompilationError("atom selector capability mismatch")
        if "atom" not in capability.supported_goal_kinds:
            raise CompilationError("capability does not support atom")
        return
    if isinstance(goal, ForEachGoal):
        selector = _selector(goal.selector_id, selectors)
        capability = catalog.capability(goal.atom.capability_id)
        if selector.cardinality != "all" or selector.capability_id != goal.atom.capability_id:
            raise CompilationError("ForEach requires an all-cardinality selector")
        if "foreach" not in capability.supported_goal_kinds:
            raise CompilationError("capability does not support ForEach")
        return
    if isinstance(goal, AllGoal):
        for child_goal in goal.children:
            _validate_goal(child_goal, selectors, catalog)
        rule = catalog.rules.get(goal.composition_rule_id)
        if rule is None:
            raise CompilationError("AllGoal has no qualified CompositionRule")
        if set(goal_capability_ids(goal)) != set(rule.capability_ids):
            raise CompilationError("AllGoal capability set does not match CompositionRule")
        return
    if isinstance(goal, IfGoal):
        owner, condition = catalog.conditions.get(goal.condition_id, (None, None))
        if condition is None or owner is None:
            raise CompilationError(f"unknown condition {goal.condition_id!r}")
        if condition.binding_scope == "selected_binding":
            if goal.selector_id is None:
                raise CompilationError("selected-binding condition requires selector_id")
            if _selector(goal.selector_id, selectors).capability_id != owner.capability_id:
                raise CompilationError("condition selector uses the wrong capability")
        elif goal.selector_id is not None:
            raise CompilationError("world condition must not carry a binding selector")
        branches = (
            (goal.then_goal, condition.true_capability_ids),
            (goal.else_goal, condition.false_capability_ids),
        )
        for branch_goal, allowed_capability_ids in branches:
            if branch_goal is None:
                if condition.report_field is None:
                    raise CompilationError("goal-less condition branch lacks a qualified report")
                continue
            _validate_goal(branch_goal, selectors, catalog)
            if not set(goal_capability_ids(branch_goal)) <= set(allowed_capability_ids):
                raise CompilationError("condition branch uses an unlicensed capability")
        return
    raise CompilationError(f"unsupported goal type {type(goal).__name__}")


'''
    text = replace_between(
        text,
        "def _validate_goal(\n",
        "def _selector(\n",
        validate_goal,
        label="compiler goal validation",
    )
    text = replace_once(
        text,
        "    if isinstance(goal, AllGoal):\n"
        "        return \"; also \".join(\n"
        "            _render_goal(child, blueprint, catalog, resolved, bindings) for child in goal.children\n"
        "        )\n"
        "    _, condition = catalog.conditions[goal.condition_id]\n"
        "    then_text = _branch_text(goal.then_goal, condition, blueprint, catalog, resolved, bindings)\n"
        "    else_text = _branch_text(goal.else_goal, condition, blueprint, catalog, resolved, bindings)\n"
        "    return f\"if {condition.public_label}, {then_text}; otherwise, {else_text}\"\n",
        "    if isinstance(goal, AllGoal):\n"
        "        return \"; also \".join(\n"
        "            _render_goal(child_goal, blueprint, catalog, resolved, bindings)\n"
        "            for child_goal in goal.children\n"
        "        )\n"
        "    if isinstance(goal, IfGoal):\n"
        "        _, condition = catalog.conditions[goal.condition_id]\n"
        "        then_text = _branch_text(\n"
        "            goal.then_goal, condition, blueprint, catalog, resolved, bindings\n"
        "        )\n"
        "        else_text = _branch_text(\n"
        "            goal.else_goal, condition, blueprint, catalog, resolved, bindings\n"
        "        )\n"
        "        return f\"if {condition.public_label}, {then_text}; otherwise, {else_text}\"\n"
        "    raise CompilationError(f\"unsupported goal type {type(goal).__name__}\")\n",
        label="renderer exhaustive goal dispatch",
    )
    path.write_text(text, encoding="utf-8")


def patch_foundry() -> None:
    path = ROOT / "src/agent_task_foundry/foundry.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from agent_task_foundry.compiler import CompiledTaskChecker, compile_definition\n",
        "from agent_task_foundry.compiler import CompiledTaskChecker, compile_definition\n"
        "from agent_task_foundry.facets import (\n"
        "    ExtremeDirection,\n"
        "    FacetValueError,\n"
        "    compare_facet_values,\n"
        "    extreme_facet_value,\n"
        ")\n",
        label="foundry facet imports",
    )
    old = '''    for facet in capability.facets:
        if "max" not in facet.allowed_operators and "min" not in facet.allowed_operators:
            continue
        values = [item.facets.get(facet.name) for item in candidates]
        for direction in ("max", "min"):
            if direction not in facet.allowed_operators:
                continue
            try:
                target = max(values) if direction == "max" else min(values)
            except TypeError:
                continue
            matches = [item for item in candidates if item.facets.get(facet.name) == target]
            if len(matches) == 1 and matches[0] == candidate:
                return SelectorSpec(
                    f"{capability.capability_id}:{facet.name}:{direction}",
                    capability.capability_id,
                    rank=RankSpec(facet.name, direction),
                )
'''
    new = '''    directions: tuple[ExtremeDirection, ...] = ("max", "min")
    for facet in capability.facets:
        if "max" not in facet.allowed_operators and "min" not in facet.allowed_operators:
            continue
        values = [item.facets.get(facet.name) for item in candidates]
        for direction in directions:
            if direction not in facet.allowed_operators:
                continue
            try:
                target = extreme_facet_value(values, direction)
            except FacetValueError as exc:
                raise SynthesisError(
                    f"qualified rank facet {facet.name!r} is not comparable: {exc}"
                ) from exc
            matches = [
                item
                for item in candidates
                if compare_facet_values(item.facets.get(facet.name), "eq", target)
            ]
            if len(matches) == 1 and matches[0] == candidate:
                return SelectorSpec(
                    f"{capability.capability_id}:{facet.name}:{direction}",
                    capability.capability_id,
                    rank=RankSpec(facet.name, direction),
                )
'''
    text = replace_once(text, old, new, label="foundry comparable rank selector")
    path.write_text(text, encoding="utf-8")


def patch_runner() -> None:
    path = ROOT / "src/agent_task_foundry/runner.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from collections.abc import Callable, Mapping, Sequence\n"
        "from dataclasses import dataclass\n"
        "from typing import Any, Protocol, cast\n\n"
        "from agent_env_foundry.semantics import JSONObject, JSONValue, TraceEvent\n",
        "from collections.abc import Callable, Mapping\n"
        "from dataclasses import dataclass\n"
        "from typing import Any, Protocol, cast\n\n"
        "from openai import OpenAI\n"
        "from openai.types.responses import (\n"
        "    EasyInputMessageParam,\n"
        "    FunctionToolParam,\n"
        "    ResponseFunctionToolCall,\n"
        "    ResponseInputItemParam,\n"
        "    ResponseInputParam,\n"
        "    ResponseOutputItem,\n"
        ")\n"
        "from openai.types.responses.response_input_param import FunctionCallOutput\n\n"
        "from agent_env_foundry.jsonvalue import is_json_object\n"
        "from agent_env_foundry.semantics import JSONObject, JSONValue, TraceEvent\n",
        label="runner official type imports",
    )
    text = replace_once(
        text,
        "PolicyDecision = PolicyAction | PolicyFinish\n"
        "Policy = Callable[[TaskDefinition, JSONValue, tuple[PublicTraceEvent, ...]], PolicyDecision]\n\n\n",
        "PolicyDecision = PolicyAction | PolicyFinish\n"
        "Policy = Callable[[TaskDefinition, JSONValue, tuple[PublicTraceEvent, ...]], PolicyDecision]\n\n\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class _ResponseTurn:\n"
        "    output: tuple[ResponseOutputItem, ...]\n"
        "    output_text: str\n\n\n"
        "ResponseTurnCreator = Callable[[ResponseInputParam, list[FunctionToolParam]], _ResponseTurn]\n\n\n",
        label="runner response turn contract",
    )
    replacement = '''def run_responses_policy(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    model: str,
    base_url: str,
    materialization_id: str,
    max_steps: int = 20,
) -> WitnessRun:
    """Run the final instruction with an OpenAI Responses function-tool loop."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is required for Responses execution")
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def create_turn(
        input_items: ResponseInputParam,
        functions: list[FunctionToolParam],
    ) -> _ResponseTurn:
        response = client.responses.create(
            model=model,
            input=input_items,
            tools=functions,
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
        )
        return _ResponseTurn(tuple(response.output), response.output_text or "")

    return _run_responses_policy_loop(
        actor=actor,
        definition=definition,
        checker=checker,
        before_facts=before_facts,
        after_facts=after_facts,
        create_turn=create_turn,
        materialization_id=materialization_id,
        max_steps=max_steps,
    )


def _run_responses_policy_loop(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    create_turn: ResponseTurnCreator,
    materialization_id: str,
    max_steps: int = 20,
) -> WitnessRun:
    """Execute typed Responses turns; injectable creator supports deterministic tests."""

    reset_context = actor.reset(definition.blueprint.start_recipe.reset_input)
    if not _contains(reset_context, definition.public_reset_context):
        raise RunnerError("fresh reset context omits a TaskDefinition public fact")
    tools = tuple(actor.tools())
    functions = [_responses_tool(spec) for spec in tools]
    initial_message: EasyInputMessageParam = {
        "role": "user",
        "content": json.dumps(
            {
                "instruction": definition.instruction,
                "reset_context": reset_context,
                "answer_schema": definition.answer_schema,
            },
            ensure_ascii=False,
        ),
    }
    history: ResponseInputParam = [initial_message]
    public_trace: list[PublicTraceEvent] = []
    final_answer: JSONValue = None
    for _ in range(max_steps + 1):
        turn = create_turn(history, functions)
        history.extend(_response_output_as_input(item) for item in turn.output)
        calls = [item for item in turn.output if isinstance(item, ResponseFunctionToolCall)]
        if not calls:
            if not turn.output_text.strip():
                raise RunnerError("Responses policy returned neither tool call nor answer")
            try:
                parsed_answer: object = json.loads(turn.output_text)
            except json.JSONDecodeError:
                final_answer = turn.output_text
            else:
                if not _is_json_value(parsed_answer):
                    raise RunnerError("Responses final answer is not a JSON value")
                final_answer = cast(JSONValue, parsed_answer)
            break
        for call in calls:
            try:
                parsed_arguments: object = json.loads(call.arguments)
            except json.JSONDecodeError as exc:
                raise RunnerError("tool arguments are not valid JSON") from exc
            if not is_json_object(parsed_arguments):
                raise RunnerError("tool arguments must be an object")
            arguments = cast(JSONObject, parsed_arguments)
            spec = _tool_spec(tools, call.name)
            provenance = trace_argument_provenance(
                arguments=arguments,
                instruction_literals=_task_literals(definition),
                reset_context=reset_context,
                tool_spec=spec,
                prior_trace=tuple(public_trace),
            )
            raw_observation = dict(actor.invoke(call.name, arguments))
            if set(raw_observation) != {"ok", "data", "error"} or not is_json_object(
                raw_observation
            ):
                raise RunnerError("actor returned a malformed ToolObservation")
            observation = cast(JSONObject, raw_observation)
            public_trace.append(
                PublicTraceEvent(
                    len(public_trace) + 1,
                    call.name,
                    arguments,
                    observation,
                    provenance,
                )
            )
            function_output: FunctionCallOutput = {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(observation, ensure_ascii=False, sort_keys=True),
            }
            history.append(function_output)
    else:
        raise RunnerError("Responses policy exceeded max_steps")
    semantic_trace = tuple(
        TraceEvent(item.seq, item.tool_name, item.arguments, item.observation)
        for item in public_trace
    )
    result = checker.evaluate(before_facts, after_facts(), semantic_trace, final_answer)
    return WitnessRun(
        uuid.uuid4().hex,
        materialization_id,
        definition.task_definition_id,
        tuple(public_trace),
        final_answer,
        result.status,
        result.failures,
    )


def _response_output_as_input(item: ResponseOutputItem) -> ResponseInputItemParam:
    """Convert one validated SDK output model to its official input-item shape."""

    document = item.model_dump(mode="json", exclude_none=True)
    item_type = document.get("type") if isinstance(document, dict) else None
    if not isinstance(item_type, str):
        raise RunnerError("Responses output item lacks a typed input representation")
    return cast(ResponseInputItemParam, document)


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


'''
    text = replace_between(
        text,
        "def run_responses_policy(\n",
        "def _task_literals(\n",
        replacement,
        label="runner typed Responses loop",
    )
    old_tool = '''def _responses_tool(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec["name"],
        "description": spec.get("description", ""),
        "parameters": spec["input_schema"],
        "strict": True,
    }
'''
    new_tool = '''def _responses_tool(spec: Mapping[str, Any]) -> FunctionToolParam:
    name = spec.get("name")
    description = spec.get("description", "")
    parameters_value = spec.get("input_schema")
    if not isinstance(name, str) or not name:
        raise RunnerError("ToolSpec name must be a non-empty string")
    if not isinstance(description, str):
        raise RunnerError(f"ToolSpec {name!r} description must be a string")
    if not isinstance(parameters_value, dict):
        raise RunnerError(f"ToolSpec {name!r} input_schema must be an object")
    parameters: dict[str, object] = {
        str(key): value for key, value in parameters_value.items()
    }
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": True,
    }
'''
    text = replace_once(text, old_tool, new_tool, label="runner FunctionToolParam")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_compiler()
    patch_foundry()
    patch_runner()


if __name__ == "__main__":
    main()

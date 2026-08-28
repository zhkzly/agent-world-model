from agent_task_foundry.runner import trace_argument_provenance


def test_no_argument_tool_has_vacuously_complete_provenance() -> None:
    report = trace_argument_provenance(
        arguments={},
        instruction_literals=(),
        reset_context={},
        tool_spec={"input_schema": {"type": "object", "properties": {}}},
        prior_trace=(),
    )
    assert report.complete

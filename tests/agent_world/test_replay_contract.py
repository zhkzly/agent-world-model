from agent_world.replay_contract import normalise_framework_replay_calls


def test_normalise_framework_replay_calls_accepts_list_shape():
    task = {
        "framework_replay": [
            {"tool_id": "op_create_work_item", "input": {"title": "A"}},
            {"logical_tool_id": "op_add_shift_note", "arguments": {"note": "handoff"}},
        ],
        "dependency_path": ["op_create_work_item", "op_add_shift_note"],
    }

    assert normalise_framework_replay_calls(task) == [
        {"tool": "op_create_work_item", "kwargs": {"title": "A"}},
        {"tool": "op_add_shift_note", "kwargs": {"note": "handoff"}},
    ]


def test_normalise_framework_replay_calls_falls_back_to_dependency_path():
    task = {"framework_replay": [], "dependency_path": ["op_query_summary"]}

    assert normalise_framework_replay_calls(task) == [{"tool": "op_query_summary", "kwargs": {}}]

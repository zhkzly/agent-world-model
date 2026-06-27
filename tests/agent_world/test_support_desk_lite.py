from agent_world.fixtures.support_desk_lite import (
    SupportDeskLite,
    create_seed_db,
    reset_environment,
    verify_task_completion,
)


def test_support_desk_python_surface_and_state_diff_verifier(tmp_path):
    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    trace = tmp_path / "trace.jsonl"
    surface = SupportDeskLite(final, trace_path=trace, task_id="task-1")

    matches = surface.search_tickets(status="open", customer_tier="vip", keyword="refund")
    assert [ticket["id"] for ticket in matches] == ["T-100", "T-102"]

    surface.get_ticket("T-100")
    surface.add_ticket_note(ticket_id="T-100", visibility="internal", body="Refund follow-up queued with billing.")
    result = verify_task_completion("task-1", seed, final, surface_trace_path=trace)

    assert result["success"] is True


def test_support_desk_read_only_verifier_requires_no_state_change(tmp_path):
    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    trace = tmp_path / "trace.jsonl"
    surface = SupportDeskLite(final, trace_path=trace, task_id="task-4")
    surface.search_tickets(status="open", customer_tier="vip")
    answer = {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"}

    result = verify_task_completion("task-4", seed, final, final_answer=answer, surface_trace_path=trace)

    assert result["success"] is True


def test_support_desk_verifier_rejects_wrong_assignment(tmp_path):
    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    surface = SupportDeskLite(final)
    surface.assign_ticket(ticket_id="T-101", queue="enterprise-support", assignee="not-iris", note="Moved queue only.")

    result = verify_task_completion("task-2", seed, final)

    assert result["success"] is False
    assert any(check["name"] == "target_assignee_changed" and check["passed"] is False for check in result["checks"])


def test_support_desk_verifier_rejects_non_target_mutation(tmp_path):
    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    surface = SupportDeskLite(final)
    surface.assign_ticket(ticket_id="T-101", queue="enterprise-support", assignee="iris", note="Moved to enterprise support.")
    surface.update_ticket_priority(ticket_id="T-100", priority="high", note="Unrelated mutation.")

    result = verify_task_completion("task-2", seed, final)

    assert result["success"] is False
    assert any(check["name"] == "non_target_records_unchanged" and check["passed"] is False for check in result["checks"])


def test_support_desk_verifier_rejects_extra_trace_calls(tmp_path):
    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    trace = tmp_path / "trace.jsonl"
    surface = SupportDeskLite(final, trace_path=trace, task_id="task-1")
    surface.search_tickets(status="open", customer_tier="vip", keyword="refund")
    surface.get_ticket("T-100")
    surface.search_tickets(status="open")
    surface.add_ticket_note(ticket_id="T-100", visibility="internal", body="Refund follow-up queued with billing.")

    result = verify_task_completion("task-1", seed, final, surface_trace_path=trace)

    assert result["success"] is False
    assert any(check["name"] == "dependency_path_trace_matches" and check["passed"] is False for check in result["checks"])

"""Checkpoint A acceptance for the no-Graph common Goal evaluator.

The values are reduced copies of the frozen inventory, support, Git, and
laboratory Release/3 planning probes; they are not invented domain fixtures.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.task_goal import (
    AllGoal,
    AtomGoal,
    EvaluationContext,
    ForEachGoal,
    GoalTruth,
    GoalValueSource,
    IfGoal,
    ScalarCondition,
    TraceEvent,
    evaluate_goal,
    goal_truth_from_document,
)


def _ok(data: object) -> dict[str, object]:
    return {"ok": True, "data": data, "error": None}


def _refusal(code: str) -> dict[str, object]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": "domain refusal"},
    }


def _event(
    seq: int,
    tool: str,
    arguments: dict[str, object],
    observation: dict[str, object],
) -> TraceEvent:
    return TraceEvent(seq, tool, arguments, observation)


def _schema(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _truth(
    goal: object,
    *,
    before: object,
    after: object,
    answer: dict[str, object],
    answer_schema: dict[str, object],
    reset: object = None,
) -> GoalTruth:
    return GoalTruth(
        goal=goal,
        expected_reset=reset,
        expected_before=before,
        expected_after=after,
        expected_answer=answer,
        final_answer_schema=answer_schema,
    )


def _context(
    *,
    before: object,
    after: object,
    trace: tuple[TraceEvent, ...],
    answer: dict[str, object],
    reset: object = None,
) -> EvaluationContext:
    return EvaluationContext(
        reset_observation=reset,
        before_state=before,
        after_state=after,
        trace=trace,
        final_answer=answer,
    )


def test_real_derived_atom_query_transition_and_refusal_are_evaluated() -> None:
    query = AtomGoal("list-items", {}, "query")
    query_truth = _truth(
        query,
        before={"revision": 0},
        after={"revision": 0},
        answer={"count": 4},
        answer_schema=_schema({"count": {"type": "integer"}}),
    )
    query_context = _context(
        before={"revision": 0},
        after={"revision": 0},
        trace=(_event(1, "list-items", {}, _ok({"items": [1, 2, 3, 4]})),),
        answer={"count": 4},
    )
    assert evaluate_goal(query_truth, query_context).passed

    # EnvironmentRelease e31e08...: receive the unique collected sample.
    arguments = {
        "sample_id": "S-COLLECTED",
        "custodian_id": "CUST-RECEIVER",
        "destination_location_id": "LOC-INTAKE",
    }
    transition = AtomGoal("receive_sample", arguments, "transition")
    transition_truth = _truth(
        transition,
        before={"samples": {"S-COLLECTED": {"state": "collected"}}},
        after={
            "samples": {
                "S-COLLECTED": {
                    "state": "received",
                    "custodian_id": "CUST-RECEIVER",
                    "location_id": "LOC-INTAKE",
                }
            }
        },
        answer={"sample_id": "S-COLLECTED", "state": "received"},
        answer_schema=_schema({"sample_id": {"type": "string"}, "state": {"type": "string"}}),
    )
    transition_context = _context(
        before=transition_truth.expected_before,
        after=transition_truth.expected_after,
        trace=(
            _event(
                1,
                "receive_sample",
                arguments,
                _ok(
                    {
                        "sample_id": "S-COLLECTED",
                        "state": "received",
                        "event_id": "E-1001",
                    }
                ),
            ),
        ),
        answer={"sample_id": "S-COLLECTED", "state": "received"},
    )
    assert evaluate_goal(transition_truth, transition_context).passed

    refusal = AtomGoal(
        "reserve",
        {"reservation_id": "R-NEW", "item_id": "ZERO-01", "quantity": 1},
        "refusal",
        error_code="inventory.insufficient_stock",
    )
    refusal_truth = _truth(
        refusal,
        before={"logical_revision": 0},
        after={"logical_revision": 0},
        answer={"code": "inventory.insufficient_stock"},
        answer_schema=_schema({"code": {"type": "string"}}),
    )
    refusal_context = _context(
        before=refusal_truth.expected_before,
        after=refusal_truth.expected_after,
        trace=(
            _event(
                1,
                "reserve",
                refusal.arguments,
                _refusal("inventory.insufficient_stock"),
            ),
        ),
        answer={"code": "inventory.insufficient_stock"},
    )
    assert evaluate_goal(refusal_truth, refusal_context).passed


def test_git_all_requires_both_objectives_and_exact_state_and_answer() -> None:
    # EnvironmentRelease 6411e0...: update_release must precede a non-empty commit.
    update = AtomGoal(
        "update_release",
        {"path": "CHANGELOG.md", "marker": "v1.0.1"},
        "transition",
    )
    commit = AtomGoal("commit", {"message": "Release v1.0.1"}, "transition")
    goal = AllGoal((update, commit))
    before = {
        "head": "02e43d9",
        "release_marker": "v1.0.0",
        "tracked": {"CHANGELOG.md": "## Release: v1.0.0"},
    }
    after = {
        "head": "b562942",
        "release_marker": "v1.0.1",
        "tracked": {"CHANGELOG.md": "## Release: v1.0.1"},
    }
    answer = {"marker": "v1.0.1", "commit_id": "b562942"}
    truth = _truth(
        goal,
        before=before,
        after=after,
        answer=answer,
        answer_schema=_schema({"marker": {"type": "string"}, "commit_id": {"type": "string"}}),
    )
    complete = _context(
        before=before,
        after=after,
        trace=(
            _event(1, update.tool_name, update.arguments, _ok({"marker": "v1.0.1"})),
            _event(2, commit.tool_name, commit.arguments, _ok({"id": "b562942"})),
        ),
        answer=answer,
    )
    assert evaluate_goal(truth, complete).passed

    missing_child = replace(complete, trace=complete.trace[:1])
    assert "goal_unsatisfied" in evaluate_goal(truth, missing_child).reason_codes

    wrong_answer = replace(complete, final_answer={"marker": "v1.0.1", "commit_id": "wrong"})
    assert "answer_mismatch" in evaluate_goal(truth, wrong_answer).reason_codes

    collateral = replace(
        complete,
        after_state={**after, "tracked": {**after["tracked"], "README.md": "changed"}},
    )
    assert "after_state_mismatch" in evaluate_goal(truth, collateral).reason_codes


def test_support_if_requires_a_prior_public_scalar_and_selected_branch() -> None:
    inspect_arguments = {"ticket_id": "ticket-2"}
    source = GoalValueSource.observation(
        "inspect_ticket",
        inspect_arguments,
        "/data/assignee_id",
    )
    condition = ScalarCondition(source, "eq", None)
    assign = AtomGoal(
        "assign_ticket",
        {"ticket_id": "ticket-2", "assignee_id": "agent-1"},
        "transition",
    )
    goal = IfGoal(condition, then_goal=assign, else_goal=None)
    before = {"tickets": {"ticket-2": {"assignee_id": None, "status": "open"}}}
    after = {"tickets": {"ticket-2": {"assignee_id": "agent-1", "status": "open"}}}
    answer = {"ticket_id": "ticket-2", "assignee_id": "agent-1"}
    truth = _truth(
        goal,
        before=before,
        after=after,
        answer=answer,
        answer_schema=_schema({"ticket_id": {"type": "string"}, "assignee_id": {"type": "string"}}),
    )
    valid = _context(
        before=before,
        after=after,
        trace=(
            _event(
                1,
                "inspect_ticket",
                inspect_arguments,
                _ok({"ticket_id": "ticket-2", "assignee_id": None, "status": "open"}),
            ),
            _event(2, assign.tool_name, assign.arguments, _ok({"assignee_id": "agent-1"})),
        ),
        answer=answer,
    )
    assert evaluate_goal(truth, valid).passed

    missing_branch = replace(valid, trace=valid.trace[:1])
    assert "goal_unsatisfied" in evaluate_goal(truth, missing_branch).reason_codes

    collection_condition = IfGoal(
        ScalarCondition(
            GoalValueSource.observation("list_tickets", {}, "/data/tickets"),
            "eq",
            None,
        ),
        then_goal=assign,
        else_goal=None,
    )
    collection_truth = replace(truth, goal=collection_condition)
    collection_context = replace(
        valid,
        trace=(
            _event(1, "list_tickets", {}, _ok({"tickets": [{"ticket_id": "ticket-2"}]})),
            valid.trace[1],
        ),
    )
    assert (
        "condition_not_scalar" in evaluate_goal(collection_truth, collection_context).reason_codes
    )

    # A frozen If shape may legitimately take a non-mutating else branch.
    report = AtomGoal("inspect_ticket", inspect_arguments, "query")
    false_goal = IfGoal(condition, then_goal=assign, else_goal=report)
    false_before = {"tickets": {"ticket-2": {"assignee_id": "agent-1", "status": "open"}}}
    false_answer = {"ticket_id": "ticket-2", "assignee_id": "agent-1"}
    false_truth = _truth(
        false_goal,
        before=false_before,
        after=false_before,
        answer=false_answer,
        answer_schema=_schema({"ticket_id": {"type": "string"}, "assignee_id": {"type": "string"}}),
    )
    false_context = _context(
        before=false_before,
        after=false_before,
        trace=(
            _event(
                1,
                "inspect_ticket",
                inspect_arguments,
                _ok({"ticket_id": "ticket-2", "assignee_id": "agent-1"}),
            ),
            _event(
                2,
                "inspect_ticket",
                inspect_arguments,
                _ok({"ticket_id": "ticket-2", "assignee_id": "agent-1"}),
            ),
        ),
        answer=false_answer,
    )
    assert evaluate_goal(false_truth, false_context).passed


def test_inventory_foreach_requires_exact_initial_member_bijection() -> None:
    source = GoalValueSource.observation("list-reservations", {}, "/data/reservations")
    first = AtomGoal(
        "release",
        {"reservation_id": "INSUFFICIENT-RESERVATION-01"},
        "transition",
    )
    second = AtomGoal(
        "release",
        {"reservation_id": "SEED-RESERVATION-01"},
        "transition",
    )
    goal = ForEachGoal(
        source,
        member_key_pointer="/reservation_id",
        member_argument_pointer="/reservation_id",
        children=(first, second),
    )
    before = {"reservations": ["INSUFFICIENT-RESERVATION-01", "SEED-RESERVATION-01"]}
    after = {"reservations": []}
    answer = {"reservations": []}
    truth = _truth(
        goal,
        before=before,
        after=after,
        answer=answer,
        answer_schema=_schema({"reservations": {"type": "array", "items": {"type": "string"}}}),
    )
    members = _event(
        1,
        "list-reservations",
        {},
        _ok(
            {
                "reservations": [
                    {"reservation_id": "INSUFFICIENT-RESERVATION-01"},
                    {"reservation_id": "SEED-RESERVATION-01"},
                ]
            }
        ),
    )
    valid = _context(
        before=before,
        after=after,
        trace=(
            members,
            _event(2, first.tool_name, first.arguments, _ok({"released": first.arguments})),
            _event(3, second.tool_name, second.arguments, _ok({"released": second.arguments})),
        ),
        answer=answer,
    )
    assert evaluate_goal(truth, valid).passed

    missing = replace(valid, trace=valid.trace[:2])
    assert "foreach_members_mismatch" in evaluate_goal(truth, missing).reason_codes

    duplicate = replace(valid, trace=(members, valid.trace[1], replace(valid.trace[1], seq=3)))
    assert "foreach_members_mismatch" in evaluate_goal(truth, duplicate).reason_codes

    extra = replace(
        valid,
        trace=valid.trace
        + (
            _event(
                4,
                "release",
                {"reservation_id": "UNLISTED"},
                _ok({"released": {"reservation_id": "UNLISTED"}}),
            ),
        ),
    )
    assert "foreach_members_mismatch" in evaluate_goal(truth, extra).reason_codes


def test_goal_truth_round_trip_is_exact_and_identity_bearing() -> None:
    goal = AtomGoal("list-items", {}, "query")
    truth = _truth(
        goal,
        before={"revision": 0},
        after={"revision": 0},
        answer={"items": []},
        answer_schema=_schema({"items": {"type": "array", "items": {"type": "string"}}}),
        reset={"status": "reset"},
    )

    decoded = goal_truth_from_document(truth.to_document())

    assert decoded == truth
    assert decoded.truth_id == truth.truth_id
    with pytest.raises(ValueError, match="invalid fields"):
        goal_truth_from_document({**truth.to_document(), "legacy_checker": {}})


def test_transition_goal_cannot_freeze_a_noop_reference() -> None:
    with pytest.raises(ValueError, match="transition Goal requires a state change"):
        _truth(
            AtomGoal("commit", {"message": "empty"}, "transition"),
            before={"head": "same"},
            after={"head": "same"},
            answer={"id": "same"},
            answer_schema=_schema({"id": {"type": "string"}}),
        )

"""Checkpoint A2 contracts derived from the no-Graph live probes."""

from __future__ import annotations

import pytest

from agent_env_foundry.task_draft import (
    AllDraft,
    AnswerProjection,
    AtomDraft,
    ForEachDraft,
    IfDraft,
    PublicValueRef,
    SamplingTarget,
    TaskDraft,
    materialize_answer,
    sampling_target_from_document,
    task_draft_from_document,
)
from agent_env_foundry.task_goal import TraceEvent


def _ok(data: object) -> dict[str, object]:
    return {"ok": True, "data": data, "error": None}


def _event(seq: int, tool: str, data: object) -> TraceEvent:
    return TraceEvent(seq, tool, {}, _ok(data))


def test_sampling_target_is_required_no_graph_data_and_round_trips() -> None:
    target = SamplingTarget(
        required_goal_shape="foreach",
        required_focus_tools=("release",),
        required_outcome="transition",
        prior_structure_ids=("a" * 64,),
    )

    decoded = sampling_target_from_document(target.to_document())

    assert decoded == target
    assert decoded.target_id == target.target_id
    assert set(target.to_document()) == {
        "format",
        "required_goal_shape",
        "required_focus_tools",
        "required_outcome",
        "prior_structure_ids",
    }
    with pytest.raises(ValueError, match="invalid fields"):
        sampling_target_from_document({**target.to_document(), "tool_graph": []})


def test_task_draft_has_no_answer_schema_checker_or_expected_state() -> None:
    target = SamplingTarget("all", ("update_release", "commit"), "transition")
    draft = TaskDraft(
        sampling_target_id=target.target_id,
        instruction="Update CHANGELOG.md to v1.0.1 and commit with message Release v1.0.1.",
        goal=AllDraft((AtomDraft(6), AtomDraft(7))),
        answer=AnswerProjection.from_object(
            {
                "marker": AnswerProjection.from_source(
                    PublicValueRef.observation(9, "/data/marker")
                ),
                "commit": AnswerProjection.from_source(
                    PublicValueRef.observation(10, "/data/commits/1")
                ),
            }
        ),
    )

    decoded = task_draft_from_document(draft.to_document())

    assert decoded == draft
    assert decoded.draft_id == draft.draft_id
    document = draft.to_document()
    assert set(document) == {"format", "sampling_target_id", "instruction", "goal", "answer"}
    assert all(
        forbidden not in str(document)
        for forbidden in ("answer_schema", "checker", "expected_state", "reward")
    )
    with pytest.raises(ValueError, match="invalid fields"):
        task_draft_from_document({**document, "checker_brief": "legacy"})


def test_answer_projection_copies_public_json_and_derives_type_only_schema() -> None:
    # EnvironmentRelease a2ec57... after releasing both initial reservations.
    trace = (
        _event(
            4,
            "release",
            {
                "released_reservation": {
                    "reservation_id": "INSUFFICIENT-RESERVATION-01",
                    "item_id": "INSUFFICIENT-01",
                    "quantity": 2,
                }
            },
        ),
        _event(
            5,
            "release",
            {
                "released_reservation": {
                    "reservation_id": "SEED-RESERVATION-01",
                    "item_id": "RESERVED-01",
                    "quantity": 6,
                }
            },
        ),
        _event(6, "list-reservations", {"reservations": []}),
    )
    reservation_schema = {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string", "minLength": 1},
            "item_id": {"type": "string", "minLength": 1},
            "quantity": {"type": "integer", "minimum": 1},
        },
        "required": ["reservation_id", "item_id", "quantity"],
        "additionalProperties": False,
    }
    tool_specs = (
        {
            "name": "release",
            "description": "Release an active reservation.",
            "input_schema": {"type": "object"},
            "output_schema": {
                "type": "object",
                "properties": {"released_reservation": reservation_schema},
                "required": ["released_reservation"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list-reservations",
            "description": "List active reservations.",
            "input_schema": {"type": "object"},
            "output_schema": {
                "type": "object",
                "properties": {"reservations": {"type": "array", "items": reservation_schema}},
                "required": ["reservations"],
                "additionalProperties": False,
            },
        },
    )
    projection = AnswerProjection.from_object(
        {
            "released": AnswerProjection.from_array(
                (
                    AnswerProjection.from_source(
                        PublicValueRef.observation(4, "/data/released_reservation")
                    ),
                    AnswerProjection.from_source(
                        PublicValueRef.observation(5, "/data/released_reservation")
                    ),
                )
            ),
            "remaining": AnswerProjection.from_source(
                PublicValueRef.observation(6, "/data/reservations")
            ),
        }
    )

    answer = materialize_answer(
        projection,
        reset_observation={},
        reset_schema={"type": "object", "properties": {}, "additionalProperties": False},
        trace=trace,
        tool_specs=tool_specs,
    )

    assert answer.value == {
        "released": [
            {
                "reservation_id": "INSUFFICIENT-RESERVATION-01",
                "item_id": "INSUFFICIENT-01",
                "quantity": 2,
            },
            {
                "reservation_id": "SEED-RESERVATION-01",
                "item_id": "RESERVED-01",
                "quantity": 6,
            },
        ],
        "remaining": [],
    }
    assert answer.schema["properties"]["remaining"] == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "reservation_id": {"type": "string"},
                "item_id": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["reservation_id", "item_id", "quantity"],
            "additionalProperties": False,
        },
    }
    assert all(
        keyword not in str(answer.schema)
        for keyword in ("const", "pattern", "minimum", "minLength", "uniqueItems")
    )


def test_answer_projection_fails_closed_on_missing_or_untyped_sources() -> None:
    projection = AnswerProjection.from_object(
        {"value": AnswerProjection.from_source(PublicValueRef.observation(9, "/data/value"))}
    )
    with pytest.raises(ValueError, match="step 9 does not exist"):
        materialize_answer(
            projection,
            reset_observation={},
            reset_schema={"type": "object"},
            trace=(),
            tool_specs=(),
        )

    empty_literal = AnswerProjection.from_object(
        {"items": AnswerProjection.from_source(PublicValueRef.task_literal([]))}
    )
    with pytest.raises(ValueError, match="empty array requires a public source item schema"):
        materialize_answer(
            empty_literal,
            reset_observation={},
            reset_schema={"type": "object"},
            trace=(),
            tool_specs=(),
        )


def test_foreach_draft_requires_public_members_and_one_atom_per_member_slot() -> None:
    members = PublicValueRef.observation(1, "/data/reservations")
    draft = ForEachDraft(
        members=members,
        member_key_pointer="/reservation_id",
        member_argument_pointer="/reservation_id",
        children=(AtomDraft(4), AtomDraft(5)),
    )
    target = SamplingTarget("foreach", ("release",), "transition")
    task = TaskDraft(
        target.target_id,
        "Release every reservation in the initial public reservation list.",
        draft,
        AnswerProjection.from_object(
            {
                "remaining": AnswerProjection.from_source(
                    PublicValueRef.observation(6, "/data/reservations")
                )
            }
        ),
    )

    assert task_draft_from_document(task.to_document()) == task
    with pytest.raises(ValueError, match="at least two Atom children"):
        ForEachDraft(
            members,
            "/reservation_id",
            "/reservation_id",
            (AtomDraft(4),),
        )


def test_if_draft_rejects_transport_success_as_a_business_condition() -> None:
    with pytest.raises(ValueError, match="business data scalar"):
        IfDraft(
            condition=PublicValueRef.observation(1, "/ok"),
            operator="eq",
            value=True,
            then_goal=AtomDraft(2),
            else_goal=None,
        )

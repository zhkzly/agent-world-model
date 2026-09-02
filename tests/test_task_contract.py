from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskCheckResult,
    TaskProposalEvidence,
    candidate_task_contract_from_document,
    make_task_check_request,
    seal_task_contract,
    task_check_result_from_document,
    task_contract_from_document,
    task_proposal_evidence_from_document,
)


def _proposal_evidence() -> TaskProposalEvidence:
    return TaskProposalEvidence(
        format="task-proposal-evidence/1",
        release_id="1" * 64,
        reset_start=None,
        reset_observation={"request_ids": ["req-1"]},
        before_state={"requests": [{"id": "req-1", "status": "submitted"}]},
        after_state={"requests": [{"id": "req-1", "status": "approved"}]},
        public_trace=(
            {
                "tool": "approve_request",
                "arguments": {"request_id": "req-1"},
                "observation": {
                    "ok": True,
                    "data": {"request_id": "req-1", "status": "approved"},
                    "error": None,
                },
            },
        ),
        proposed_final_answer={"request_id": "req-1", "status": "approved"},
    )


def _candidate() -> CandidateTaskContract:
    evidence = _proposal_evidence()
    return CandidateTaskContract(
        format="candidate-task-contract/1",
        release_id="1" * 64,
        builder_projection_digest="2" * 64,
        reset_start=None,
        instruction="Approve the eligible request and report its final status.",
        final_answer_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["request_id", "status"],
            "additionalProperties": False,
        },
        checker_brief=(
            "Pass only when the selected request changes from submitted to approved, "
            "unrelated records stay unchanged, and the answer reports its exact ID/status."
        ),
        proposal_evidence_digest=evidence.evidence_id,
    )


def test_candidate_identity_binds_semantics_but_not_future_witnesses() -> None:
    candidate = _candidate()

    assert candidate.candidate_id
    assert replace(candidate, instruction=candidate.instruction + " Now.").candidate_id != (
        candidate.candidate_id
    )
    assert replace(candidate, proposal_evidence_digest="4" * 64).candidate_id != (
        candidate.candidate_id
    )
    assert replace(candidate, reset_start={"case": "submitted"}).candidate_id != (
        candidate.candidate_id
    )
    assert "witness" not in candidate.to_document()
    assert "assessment" not in candidate.to_document()


def test_proposal_evidence_is_physical_preimage_not_a_verdict() -> None:
    evidence = _proposal_evidence()

    assert evidence.evidence_id
    assert evidence.before_state != evidence.after_state
    assert not {"passed", "reward", "checker_result", "witness"} & set(evidence.to_document())
    changed = replace(evidence, proposed_final_answer={"request_id": "req-1", "status": "wrong"})
    assert changed.evidence_id != evidence.evidence_id


def test_sealed_task_has_one_checker_authority_and_nonleaking_public_projection() -> None:
    candidate = _candidate()
    task = seal_task_contract(
        candidate,
        checker_project_digest="a" * 64,
        checker_factory="generated_task_checker.release:check_task",
    )

    assert task.candidate_id == candidate.candidate_id
    assert task.task_id
    public = task.public_document()
    assert public == {
        "format": "public-task/1",
        "task_id": task.task_id,
        "release_id": candidate.release_id,
        "instruction": candidate.instruction,
        "final_answer_schema": candidate.final_answer_schema,
    }
    assert not {
        "reset_start",
        "checker_factory",
        "checker_project_digest",
        "checker_brief",
        "proposal_evidence_digest",
    } & set(public)

    corrected = seal_task_contract(
        candidate,
        checker_project_digest="b" * 64,
        checker_factory="generated_task_checker.release:check_task",
    )
    assert corrected.task_id != task.task_id


def test_check_request_validates_final_answer_before_checker_execution() -> None:
    task = seal_task_contract(
        _candidate(),
        checker_project_digest="a" * 64,
        checker_factory="generated_task_checker.release:check_task",
    )
    request = make_task_check_request(
        task,
        before_state={"requests": [{"id": "req-1", "status": "submitted"}]},
        after_state={"requests": [{"id": "req-1", "status": "approved"}]},
        public_trace=(
            {
                "tool": "approve_request",
                "arguments": {"request_id": "req-1"},
                "observation": {
                    "ok": True,
                    "data": {"request_id": "req-1", "status": "approved"},
                    "error": None,
                },
            },
        ),
        final_answer={"request_id": "req-1", "status": "approved"},
    )

    assert request.task_id == task.task_id
    assert request.final_answer["status"] == "approved"
    with pytest.raises(ValueError, match="final answer"):
        make_task_check_request(
            task,
            before_state={},
            after_state={},
            public_trace=(),
            final_answer={"request_id": "req-1"},
        )


def test_checker_result_axes_are_the_only_pass_authority() -> None:
    result = TaskCheckResult(
        format="task-check-result/1",
        passed=False,
        goal=True,
        answer=False,
        required_effects=True,
        forbidden_effects=True,
        process=True,
        reason_codes=("answer_mismatch",),
    )
    assert task_check_result_from_document(result.to_document()) == result

    with pytest.raises(ValueError, match="passed must equal"):
        replace(result, passed=True)

    document = result.to_document()
    document["score"] = 0.5
    with pytest.raises(ValueError, match="exactly"):
        task_check_result_from_document(document)


def test_task_documents_round_trip_through_cold_exact_decoders() -> None:
    evidence = _proposal_evidence()
    candidate = _candidate()
    task = seal_task_contract(candidate, checker_project_digest="a" * 64)

    assert task_proposal_evidence_from_document(evidence.to_document()) == evidence
    assert candidate_task_contract_from_document(candidate.to_document()) == candidate
    assert task_contract_from_document(task.to_document()) == task

    tampered = task.to_document()
    tampered["legacy_field"] = True
    with pytest.raises(ValueError, match="fields"):
        task_contract_from_document(tampered)

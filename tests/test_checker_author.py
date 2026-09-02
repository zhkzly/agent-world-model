from __future__ import annotations

from pathlib import Path

import pytest

import agent_env_foundry.checker_author as checker_author_module
from agent_env_foundry.builder import BuilderConfig
from agent_env_foundry.checker_author import (
    CheckerAuthorInputError,
    compute_checker_project_digest,
    execute_checker_project,
    execute_task_checker,
    prepare_checker_author_workspace,
    run_checker_checks,
)
from agent_env_foundry.physical_runtime import PreparationSettings
from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskProposalEvidence,
    make_task_check_request,
)


def _evidence() -> TaskProposalEvidence:
    return TaskProposalEvidence(
        "task-proposal-evidence/1",
        "1" * 64,
        None,
        {"request_ids": ["req-1", "req-2"]},
        {
            "requests": [
                {"id": "req-1", "status": "submitted"},
                {"id": "req-2", "status": "submitted"},
            ]
        },
        {
            "requests": [
                {"id": "req-1", "status": "approved"},
                {"id": "req-2", "status": "submitted"},
            ]
        },
        (
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
        {"request_id": "req-1", "status": "approved"},
    )


def _candidate(evidence: TaskProposalEvidence) -> CandidateTaskContract:
    return CandidateTaskContract(
        "candidate-task-contract/1",
        evidence.release_id,
        "2" * 64,
        evidence.reset_start,
        "Approve request req-1 and report its ID and final status.",
        {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["request_id", "status"],
            "additionalProperties": False,
        },
        (
            "Pass when req-1 alone changes from submitted to approved and the answer "
            "reports req-1/approved. A public approve_request call for req-1 is required."
        ),
        evidence.evidence_id,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o644)


def _valid_project(root: Path) -> None:
    _write(
        root / "pyproject.toml",
        """[project]
name = "generated-task-checker"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
""",
    )
    _write(
        root / "uv.lock",
        """version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "generated-task-checker"
version = "0.1.0"
source = { editable = "." }
""",
    )
    _write(root / "src/generated_task_checker/__init__.py", "")
    _write(
        root / "src/generated_task_checker/release.py",
        """def check_task(request):
    before = {item["id"]: item for item in request["before_state"]["requests"]}
    after = {item["id"]: item for item in request["after_state"]["requests"]}
    answer = request["final_answer"]
    goal = after.get("req-1", {}).get("status") == "approved"
    required = before.get("req-1", {}).get("status") == "submitted" and goal
    forbidden = before.get("req-2") == after.get("req-2")
    answer_ok = answer == {"request_id": "req-1", "status": "approved"}
    process = any(
        item.get("tool") == "approve_request"
        and item.get("arguments") == {"request_id": "req-1"}
        for item in request["public_trace"]
    )
    axes = (goal, answer_ok, required, forbidden, process)
    reasons = []
    for ok, code in zip(axes, ("goal", "answer", "required", "forbidden", "process")):
        if not ok:
            reasons.append(code)
    return {
        "format": "task-check-result/1",
        "passed": all(axes),
        "goal": goal,
        "answer": answer_ok,
        "required_effects": required,
        "forbidden_effects": forbidden,
        "process": process,
        "reason_codes": sorted(reasons),
    }
""",
    )
    _write(
        root / "tests/test_checker.py",
        "from generated_task_checker.release import check_task\n\n"
        "def test_checker_is_callable():\n"
        "    assert callable(check_task)\n",
    )


def test_checker_inputs_are_frozen_and_excluded_from_project_identity(tmp_path: Path) -> None:
    evidence = _evidence()
    prepared = prepare_checker_author_workspace(
        tmp_path / "checker",
        candidate=_candidate(evidence),
        proposal_evidence=evidence,
    )
    _valid_project(prepared.root)
    first = compute_checker_project_digest(prepared.root)

    assert set(prepared.input_digests) == {
        "CANDIDATE_TASK_CONTRACT.json",
        "PROPOSAL_EVIDENCE.json",
        "TASK_CHECKER_CONTRACT.md",
    }
    assert all(
        (prepared.root / name).stat().st_mode & 0o222 == 0 for name in prepared.input_digests
    )
    contract = (prepared.root / "TASK_CHECKER_CONTRACT.md").read_text(encoding="utf-8")
    assert "identifier selected only by proposal evidence" in contract
    (prepared.root / "CANDIDATE_TASK_CONTRACT.json").chmod(0o644)
    (prepared.root / "CANDIDATE_TASK_CONTRACT.json").write_text("{}")
    assert compute_checker_project_digest(prepared.root) == first
    with pytest.raises(CheckerAuthorInputError, match="changed"):
        prepared.verify_inputs()


def test_real_checker_project_passes_host_contract_and_executes_twice(tmp_path: Path) -> None:
    evidence = _evidence()
    prepared = prepare_checker_author_workspace(
        tmp_path / "checker",
        candidate=_candidate(evidence),
        proposal_evidence=evidence,
    )
    _valid_project(prepared.root)
    config = BuilderConfig(uv_cache_dir=tmp_path / "uv-cache")
    checker_author_module._initialize_project(prepared.root, config)

    checks = run_checker_checks(prepared, config)
    digest = compute_checker_project_digest(prepared.root)
    task, result = execute_checker_project(
        prepared,
        checker_project_digest=digest,
        runtime_root=tmp_path / "runtime",
        settings=PreparationSettings(tmp_path / "uv-cache", 120.0),
    )

    assert all(item.passed for item in checks), [item.to_document() for item in checks]
    assert result.passed
    assert task.checker_project_digest == digest
    assert task.task_id
    request = make_task_check_request(
        task,
        before_state=evidence.before_state,
        after_state=evidence.after_state,
        public_trace=evidence.public_trace,
        final_answer=evidence.proposed_final_answer,
    )
    assert execute_task_checker(
        prepared.root,
        task=task,
        request=request,
        runtime_root=tmp_path / "second-runtime",
        settings=PreparationSettings(tmp_path / "uv-cache", 120.0),
    ).passed


def test_checker_source_cannot_import_actor_or_host(tmp_path: Path) -> None:
    evidence = _evidence()
    prepared = prepare_checker_author_workspace(
        tmp_path / "checker",
        candidate=_candidate(evidence),
        proposal_evidence=evidence,
    )
    _valid_project(prepared.root)
    source = prepared.root / "src/generated_task_checker/release.py"
    source.write_text("import generated_environment\nimport agent_env_foundry\n")

    checks = run_checker_checks(
        prepared,
        BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert checks[0].phase == "source_contract"
    assert not checks[0].passed
    assert "forbidden_import" in checks[0].stderr


def test_checker_cannot_hardcode_proposal_id_when_instruction_leaves_selection_open(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    candidate = CandidateTaskContract(
        "candidate-task-contract/1",
        evidence.release_id,
        "2" * 64,
        evidence.reset_start,
        "Approve one publicly submitted request and report the selected request and status.",
        {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["request_id", "status"],
            "additionalProperties": False,
        },
        "Bind the selected request from the public trace; the proposal used req-1.",
        evidence.evidence_id,
    )
    prepared = prepare_checker_author_workspace(
        tmp_path / "checker",
        candidate=candidate,
        proposal_evidence=evidence,
    )
    _valid_project(prepared.root)

    checks = run_checker_checks(
        prepared,
        BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert checks[0].phase == "source_contract"
    assert not checks[0].passed
    assert "proposal_identifier_hardcoded:req-1" in checks[0].stderr

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskCheckResult,
    TaskProposalEvidence,
    seal_task_contract,
)
from agent_env_foundry.task_pack import task_structure_id, verify_task_pack


def _write_checker(root: Path) -> str:
    files = {
        "pyproject.toml": """[project]
name = "generated-task-checker"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
""",
        "uv.lock": """version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "generated-task-checker"
version = "0.1.0"
source = { editable = "." }
""",
        "src/generated_task_checker/__init__.py": "def check_task(request): return request\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o644)
    return compute_authored_project_digest(root, "checker", require_locked_project=True)


def _build_pack(root: Path) -> tuple[Path, str]:
    pack_root = root / "pack"
    checker = pack_root / "checker"
    checker_digest = _write_checker(checker)
    evidence = TaskProposalEvidence(
        "task-proposal-evidence/1",
        "1" * 64,
        None,
        {"ids": ["item-1"]},
        {"items": [{"id": "item-1", "status": "open"}]},
        {"items": [{"id": "item-1", "status": "closed"}]},
        (
            {
                "tool": "close_item",
                "arguments": {"item_id": "item-1"},
                "observation": {
                    "ok": True,
                    "data": {"item_id": "item-1", "status": "closed"},
                    "error": None,
                },
            },
        ),
        {"item_id": "item-1", "status": "closed"},
    )
    candidate = CandidateTaskContract(
        "candidate-task-contract/1",
        "1" * 64,
        "2" * 64,
        None,
        "Close the publicly discoverable item and report its status.",
        {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "status": {"const": "closed"},
            },
            "required": ["item_id", "status"],
            "additionalProperties": False,
        },
        "Require the selected item to change from open to closed.",
        evidence.evidence_id,
    )
    task = seal_task_contract(candidate, checker_project_digest=checker_digest)
    structure_id = task_structure_id(candidate, evidence)
    result = TaskCheckResult(
        "task-check-result/1",
        True,
        True,
        True,
        True,
        True,
        True,
        (),
    )
    witnesses = []
    for index in (1, 2):
        preimage = {
            "format": "task-witness/1",
            "task_id": task.task_id,
            "release_id": task.release_id,
            "witness_index": index,
            "reset_observation": {"ids": ["item-1"]},
            "before_state": evidence.before_state,
            "after_state": evidence.after_state,
            "public_trace": list(evidence.public_trace),
            "final_answer": evidence.proposed_final_answer,
            "checker_result": result.to_document(),
            "provider_turns": 2,
            "usage": [None, None],
        }
        witnesses.append({**preimage, "witness_id": sha256_hex(canonical_bytes(preimage))})
    preimage = {
        "format": "task-pack/1",
        "candidate": candidate.to_document(),
        "proposal_evidence": evidence.to_document(),
        "task": task.to_document(),
        "structure_id": structure_id,
        "witnesses": witnesses,
    }
    pack_id = sha256_hex(canonical_bytes(preimage))
    (pack_root / "TaskPack.json").write_bytes(
        canonical_bytes({**preimage, "task_pack_id": pack_id})
    )
    return pack_root, pack_id


def test_task_pack_cold_verifies_after_relocation(tmp_path: Path) -> None:
    root, pack_id = _build_pack(tmp_path / "source")
    relocated = tmp_path / "relocated" / pack_id
    relocated.parent.mkdir()
    shutil.copytree(root, relocated)

    verified = verify_task_pack(relocated, expected_id=pack_id)

    assert verified.task_pack_id == pack_id
    assert verified.task.release_id == "1" * 64
    assert verified.task.builder_projection_digest == "2" * 64
    assert verified.task.public_document()["instruction"].startswith("Close")
    assert len(verified.witnesses) == 2


def test_task_pack_rejects_document_and_checker_tamper(tmp_path: Path) -> None:
    root, pack_id = _build_pack(tmp_path / "document")
    document_path = root / "TaskPack.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["task"]["instruction"] += " Tampered."
    document_path.write_bytes(canonical_bytes(document))
    with pytest.raises(ValueError, match="identity|candidate|Task"):
        verify_task_pack(root, expected_id=pack_id)

    root, pack_id = _build_pack(tmp_path / "checker")
    (root / "checker/src/generated_task_checker/__init__.py").write_text("TAMPERED = True\n")
    with pytest.raises(ValueError, match="checker"):
        verify_task_pack(root, expected_id=pack_id)


def _structure_case(
    *,
    instruction: str,
    before: dict,
    after: dict,
    tools: tuple[str, ...],
    answer_fields: tuple[str, ...],
    error_code: str | None = None,
) -> tuple[CandidateTaskContract, TaskProposalEvidence]:
    trace = tuple(
        {
            "tool": tool,
            "arguments": {},
            "observation": {
                "ok": error_code is None,
                "data": {} if error_code is None else None,
                "error": None if error_code is None else {"code": error_code, "message": "x"},
            },
        }
        for tool in tools
    )
    evidence = TaskProposalEvidence(
        "task-proposal-evidence/1",
        "1" * 64,
        None,
        {},
        before,
        after,
        trace,
        {field: "value" for field in answer_fields},
    )
    schema = {
        "type": "object",
        "properties": {field: {"type": "string"} for field in answer_fields},
        "required": list(answer_fields),
        "additionalProperties": False,
    }
    candidate = CandidateTaskContract(
        "candidate-task-contract/1",
        "1" * 64,
        "2" * 64,
        None,
        instruction,
        schema,
        "Check the requested public outcome.",
        evidence.evidence_id,
    )
    return candidate, evidence


def test_structure_id_collapses_checkout_paraphrase_parameter_and_report_variants() -> None:
    # Regression distilled from the real Library warmup packs 63f7dd62, 7b6cba94,
    # 58476452, fbe5b7f1, and ff159d3e: all performed one checkout.
    first = _structure_case(
        instruction="Check out an available book and report the active loan.",
        before={"books": [{"status": "available"}, {"status": "available"}], "loans": []},
        after={"books": [{"status": "checked_out"}, {"status": "available"}], "loans": [{}]},
        tools=("list_books", "checkout_book", "inspect_book"),
        answer_fields=("book_id", "loan_id", "active_loan"),
    )
    paraphrase = _structure_case(
        instruction="Select one borrowable title, borrow it, and return the resulting identifiers.",
        before={"books": [{"status": "available"}, {"status": "available"}], "loans": []},
        after={"books": [{"status": "checked_out"}, {"status": "available"}], "loans": [{}]},
        tools=("inspect_book", "list_books", "checkout_book", "list_active_loans"),
        answer_fields=("selected_book", "new_loan", "success"),
    )
    parameter_variant = _structure_case(
        instruction="Check out a different available book and report the active loan.",
        before={"books": [{"status": "available"}, {"status": "available"}], "loans": []},
        after={"books": [{"status": "available"}, {"status": "checked_out"}], "loans": [{}]},
        tools=("list_books", "checkout_book", "inspect_book"),
        answer_fields=("book_id", "loan_id", "active_loan"),
    )

    assert task_structure_id(*first) == task_structure_id(*paraphrase)
    assert task_structure_id(*first) == task_structure_id(*parameter_variant)


def test_structure_id_keeps_distinct_transition_and_refusal_outcomes() -> None:
    checkout = _structure_case(
        instruction="Check out an available book.",
        before={"books": [{"status": "available", "history": []}], "loans": []},
        after={"books": [{"status": "checked_out", "history": ["loan"]}], "loans": [{}]},
        tools=("checkout_book",),
        answer_fields=("loan_id",),
    )
    checkout_and_return = _structure_case(
        instruction="Check out and return an available book.",
        before={"books": [{"status": "available", "history": []}], "loans": []},
        after={"books": [{"status": "available", "history": ["loan"]}], "loans": [{}]},
        tools=("checkout_book", "return_book"),
        answer_fields=("loan_id",),
    )
    unavailable = _structure_case(
        instruction="Attempt an unavailable checkout and report the refusal.",
        before={"books": [{"status": "checked_out"}]},
        after={"books": [{"status": "checked_out"}]},
        tools=("checkout_book",),
        answer_fields=("error",),
        error_code="BOOK_UNAVAILABLE",
    )
    ineligible = _structure_case(
        instruction="Attempt an ineligible checkout and report the refusal.",
        before={"books": [{"status": "available"}]},
        after={"books": [{"status": "available"}]},
        tools=("checkout_book",),
        answer_fields=("error",),
        error_code="PATRON_INELIGIBLE",
    )
    unavailable_paraphrase = _structure_case(
        instruction="Show that an unavailable title cannot be borrowed.",
        before={"books": [{"status": "checked_out"}]},
        after={"books": [{"status": "checked_out"}]},
        tools=("checkout_book", "checkout_book"),
        answer_fields=("code", "state_unchanged"),
        error_code="BOOK_UNAVAILABLE",
    )

    assert task_structure_id(*checkout) != task_structure_id(*checkout_and_return)
    assert task_structure_id(*unavailable) == task_structure_id(*unavailable_paraphrase)
    assert task_structure_id(*unavailable) != task_structure_id(*ineligible)

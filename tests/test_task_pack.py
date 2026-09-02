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

"""Cold identity verification for current Direct TaskPack artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value, json_leaf_changes
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
)
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskContract,
    TaskProposalEvidence,
    candidate_task_contract_from_document,
    seal_task_contract,
    task_check_result_from_document,
    task_contract_from_document,
    task_proposal_evidence_from_document,
)

TASK_PACK_FORMAT = "task-pack/1"
_PACK_KEYS = {
    "format",
    "candidate",
    "proposal_evidence",
    "task",
    "structure_id",
    "witnesses",
    "task_pack_id",
}
_WITNESS_KEYS = {
    "format",
    "task_id",
    "release_id",
    "witness_index",
    "reset_observation",
    "before_state",
    "after_state",
    "public_trace",
    "final_answer",
    "checker_result",
    "provider_turns",
    "usage",
    "witness_id",
}


@dataclass(frozen=True, slots=True)
class VerifiedTaskPack:
    root: Path
    task_pack_id: str
    structure_id: str
    candidate: CandidateTaskContract
    proposal_evidence: TaskProposalEvidence
    task: TaskContract
    witnesses: tuple[JSONObject, ...]


def task_structure_id(
    candidate: CandidateTaskContract,
    evidence: TaskProposalEvidence,
) -> str:
    tools: list[str] = []
    outcomes: list[JSONObject] = []
    for item in evidence.public_trace:
        tool = item.get("tool")
        observation = item.get("observation")
        if not isinstance(tool, str) or not is_json_object(observation):
            raise ValueError("proposal trace cannot define a Task structure")
        observation_document = cast(JSONObject, observation)
        error = observation_document.get("error")
        tools.append(tool)
        outcomes.append(
            {
                "ok": observation_document.get("ok"),
                "error_code": error.get("code") if isinstance(error, dict) else None,
            }
        )
    properties = candidate.final_answer_schema.get("properties")
    changes = json_leaf_changes(evidence.before_state, evidence.after_state)
    projection: JSONObject = {
        "tool_sequence": cast(JSONValue, tools),
        "outcomes": cast(JSONValue, outcomes),
        "state_change_paths": cast(JSONValue, sorted({str(item["path"]) for item in changes})),
        "answer_fields": cast(
            JSONValue, sorted(properties) if isinstance(properties, dict) else []
        ),
        "reset_start": candidate.reset_start,
    }
    return sha256_hex(canonical_bytes(projection))


def verify_task_pack(root: Path, *, expected_id: str | None = None) -> VerifiedTaskPack:
    requested = Path(root)
    if requested.is_symlink() or not requested.is_dir():
        raise ValueError("TaskPack root must be a real directory")
    base = requested.resolve()
    if {item.name for item in base.iterdir()} != {"TaskPack.json", "checker"}:
        raise ValueError("TaskPack root must contain exactly TaskPack.json and checker")
    document_path = base / "TaskPack.json"
    if document_path.is_symlink() or not document_path.is_file():
        raise ValueError("TaskPack.json must be a regular file")
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"TaskPack.json is invalid: {exc}") from exc
    if not is_json_object(document) or set(document) != _PACK_KEYS:
        raise ValueError("TaskPack document has invalid fields")
    if document_path.read_bytes() != canonical_bytes(document):
        raise ValueError("TaskPack document is not canonical JSON")
    if document["format"] != TASK_PACK_FORMAT:
        raise ValueError(f"TaskPack format must be {TASK_PACK_FORMAT!r}")
    task_pack_id = _digest(document["task_pack_id"], "task_pack_id")
    preimage = {key: value for key, value in document.items() if key != "task_pack_id"}
    if sha256_hex(canonical_bytes(preimage)) != task_pack_id:
        raise ValueError("TaskPack identity mismatch")
    if expected_id is not None and _digest(expected_id, "expected TaskPack ID") != task_pack_id:
        raise ValueError("TaskPack differs from expected identity")

    candidate = candidate_task_contract_from_document(document["candidate"])
    evidence = task_proposal_evidence_from_document(document["proposal_evidence"])
    task = task_contract_from_document(document["task"])
    if evidence.release_id != candidate.release_id:
        raise ValueError("TaskPack proposal evidence belongs to another Release")
    if evidence.evidence_id != candidate.proposal_evidence_digest:
        raise ValueError("TaskPack candidate does not bind proposal evidence")
    if (
        seal_task_contract(
            candidate,
            checker_project_digest=task.checker_project_digest,
            checker_factory=task.checker_factory,
        )
        != task
    ):
        raise ValueError("TaskPack Task does not derive from its candidate")

    structure_id = _digest(document["structure_id"], "structure_id")
    if task_structure_id(candidate, evidence) != structure_id:
        raise ValueError("TaskPack structure identity mismatch")
    checker_root = base / "checker"
    try:
        checker_digest = compute_authored_project_digest(
            checker_root,
            "checker",
            require_locked_project=True,
        )
    except ProjectIdentityError as exc:
        raise ValueError(f"TaskPack checker is invalid: {exc}") from exc
    if checker_digest != task.checker_project_digest:
        raise ValueError("TaskPack checker identity mismatch")

    raw_witnesses = document["witnesses"]
    if not isinstance(raw_witnesses, list) or len(raw_witnesses) != 2:
        raise ValueError("TaskPack requires exactly two admission witnesses")
    witnesses = tuple(_verify_witness(item, task) for item in raw_witnesses)
    if tuple(item["witness_index"] for item in witnesses) != (1, 2):
        raise ValueError("TaskPack witness indices must be exactly 1 and 2")
    if len({cast(str, item["witness_id"]) for item in witnesses}) != 2:
        raise ValueError("TaskPack witnesses must have distinct identities")
    return VerifiedTaskPack(
        base,
        task_pack_id,
        structure_id,
        candidate,
        evidence,
        task,
        witnesses,
    )


def _verify_witness(document: Any, task: TaskContract) -> JSONObject:
    if not is_json_object(document) or set(document) != _WITNESS_KEYS:
        raise ValueError("TaskPack witness has invalid fields")
    value = cast(JSONObject, document)
    if value["format"] != "task-witness/1":
        raise ValueError("TaskPack witness format is invalid")
    witness_id = _digest(value["witness_id"], "witness_id")
    preimage = {key: item for key, item in value.items() if key != "witness_id"}
    if sha256_hex(canonical_bytes(preimage)) != witness_id:
        raise ValueError("TaskPack witness identity mismatch")
    if value["task_id"] != task.task_id or value["release_id"] != task.release_id:
        raise ValueError("TaskPack witness belongs to another Task or Release")
    if not isinstance(value["witness_index"], int) or isinstance(value["witness_index"], bool):
        raise ValueError("TaskPack witness_index must be an integer")
    if not is_json_value(value["reset_observation"]):
        raise ValueError("TaskPack witness reset observation is invalid")
    trace = value["public_trace"]
    if not isinstance(trace, list) or any(not is_json_object(item) for item in trace):
        raise ValueError("TaskPack witness public_trace must be an object array")
    answer = value["final_answer"]
    if not is_json_object(answer):
        raise ValueError("TaskPack witness final_answer must be an object")
    try:
        validate_instance(answer, task.final_answer_schema, role="TaskPack witness answer")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    result = task_check_result_from_document(value["checker_result"])
    if not result.passed:
        raise ValueError("TaskPack admission witness did not pass its checker")
    turns = value["provider_turns"]
    usage = value["usage"]
    if (
        not isinstance(turns, int)
        or isinstance(turns, bool)
        or turns <= 0
        or not isinstance(usage, list)
        or len(usage) != turns
    ):
        raise ValueError("TaskPack witness provider evidence is invalid")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _digest(value: Any, role: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")
    return value


__all__ = [
    "TASK_PACK_FORMAT",
    "VerifiedTaskPack",
    "task_structure_id",
    "verify_task_pack",
]

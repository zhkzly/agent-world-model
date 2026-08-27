"""Candidate-blind independent semantic Qualification (S1 Slice 4)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Never, cast

import rfc8785
from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from agent_env_foundry._qualification_runner import (
    ControlledRunCarrier,
    HostJournal,
    TreeManifest,
    _copy_release,
    _is_host_journal,
    _is_run_carrier,
    _load_host_journal,
    _make_run_carrier,
    _rebind_release_copy,
    _tree_manifest,
)
from agent_env_foundry.agents import (
    AgentRoute,
    _default_client_factory,
    _ProviderTurnBudget,
    _run_fresh_json_turn,
)
from agent_env_foundry.builder import compute_candidate_digest
from agent_env_foundry.research import BuilderProjection, ResearchFailure

EXPECTED_NAME = "EXPECTED_RELATIONS.json"
PREDICATE_NAME = "QUALIFICATION_PREDICATES.json"
VIEW_NAME = "candidate-view"
VIEW_MANIFEST_NAME = "CANDIDATE_VIEW_MANIFEST.json"
CONTRACT_NAME = "ENVIRONMENT_CONTRACT.md"
PROBE_MANIFEST_NAME = "probe_manifest.json"
PROBE_SCRIPTS = ("native_probe.py", "negative_setup.py", "public_probe.py")
CHECK_CLASSES = frozenset(
    {
        "reset_reconstruction",
        "value_chain",
        "native_before_after",
        "refusal_no_mutation",
        "instance_isolation",
        "nondefault_start_repeat",
        "reload_persistence",
    }
)
_VIEW_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "dist",
        "tests",
    }
)
_VIEW_EXCLUDED_NAMES = frozenset(
    {"BUILDER_PROJECTION.json", "ENVIRONMENT_CONTRACT.md", "AGENTS.md"}
)
_ROOT_PUBLIC = frozenset(
    {
        ".python-version",
        "pyproject.toml",
        "uv.lock",
        "release.json",
        "payload-manifest.json",
    }
)
QualificationStatus = Literal["passed", "candidate_defect", "probe_defect", "infra_failure"]
_CANDIDATE_FAILURE_CODES = frozenset(
    {
        "candidate_digest_changed",
        "candidate_digest_mismatch",
        "candidate_release_invalid",
        "candidate_runtime_failed",
    }
)


class QualificationFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase, self.code = phase, code
        self.details = {"phase": phase, **details}


def _fail(phase: str, code: str, message: str, **details: Any) -> Never:
    raise QualificationFailure(phase, code, message, **details)


@dataclass(frozen=True)
class ExpectedRelation:
    requirement_id: str
    relation: dict[str, Any]
    relation_digest: str


@dataclass(frozen=True)
class ExpectedRelations:
    relations: tuple[ExpectedRelation, ...]
    aggregate_digest: str

    @property
    def by_id(self) -> dict[str, ExpectedRelation]:
        return {item.requirement_id: item for item in self.relations}

    def to_document(self) -> dict[str, Any]:
        return {
            "format": "expected-relations/1",
            "relations": [
                {
                    "requirement_id": item.requirement_id,
                    "relation": _copy(item.relation),
                    "relation_digest": item.relation_digest,
                }
                for item in self.relations
            ],
            "aggregate_digest": self.aggregate_digest,
        }


@dataclass(frozen=True)
class ViewFile:
    path: str
    digest: str


@dataclass(frozen=True)
class CandidateViewManifest:
    candidate_digest: str
    files: tuple[ViewFile, ...]
    view_digest: str

    def to_document(self) -> dict[str, Any]:
        return {
            "format": "candidate-view/1",
            "candidate_digest": self.candidate_digest,
            "files": [{"path": item.path, "digest": item.digest} for item in self.files],
            "view_digest": self.view_digest,
        }


@dataclass
class PreparedQualificationWorkspace:
    root: Path
    candidate_root: Path
    candidate_digest: str
    expected: ExpectedRelations
    input_digests: dict[str, str]
    predicates: dict[str, dict[str, Any]] = field(default_factory=dict)
    predicate_digest: str | None = None
    view_manifest: CandidateViewManifest | None = None

    def verify_candidate_unchanged(self) -> None:
        actual = compute_candidate_digest(self.candidate_root)
        if actual != self.candidate_digest:
            raise QualificationFailure(
                "candidate_integrity",
                "candidate_digest_changed",
                "Candidate bytes changed during Qualification",
                expected_digest=self.candidate_digest,
                actual_digest=actual,
            )

    def verify_host_inputs(self) -> None:
        for name, digest in self.input_digests.items():
            _verify_readonly(self.root / name, digest, name)

    def verify_inputs(self) -> None:
        self.verify_host_inputs()
        predicate_path = self.root / PREDICATE_NAME
        if self.predicate_digest is None and predicate_path.exists():
            raise QualificationFailure(
                "qualification_input",
                "predicate_carrier_unbound",
                "Qualifier predicates exist without Host validation",
            )
        view = self.root / VIEW_NAME
        manifest_path = self.root / VIEW_MANIFEST_NAME
        if self.view_manifest is None:
            if view.exists() or manifest_path.exists():
                raise QualificationFailure(
                    "qualification_input",
                    "candidate_view_staged_early",
                    "Candidate view exists before Host-frozen predicates",
                )
            return
        actual = {
            path.relative_to(view).as_posix()
            for path in view.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        expected = {item.path for item in self.view_manifest.files}
        if actual != expected:
            raise QualificationFailure(
                "qualification_input",
                "candidate_view_members_changed",
                "Candidate view members differ from its Host manifest",
                expected=sorted(expected),
                actual=sorted(actual),
            )
        directories = (view, *(path for path in view.rglob("*") if path.is_dir()))
        if any(stat.S_IMODE(path.stat().st_mode) != 0o555 for path in directories):
            raise QualificationFailure(
                "qualification_input",
                "candidate_view_directory_writable",
                "Candidate view directories must remain read-only",
            )
        for item in self.view_manifest.files:
            _verify_readonly(view / item.path, item.digest, "candidate view member")

    def stage_candidate_view(self) -> CandidateViewManifest:
        if self.predicate_digest is None:
            raise QualificationFailure(
                "qualification_input",
                "predicates_not_frozen",
                "Candidate view cannot be staged before Host-frozen predicates",
            )
        if self.view_manifest is not None:
            raise QualificationFailure(
                "qualification_input",
                "candidate_view_already_staged",
                "Candidate view was already staged",
            )
        self.verify_host_inputs()
        self.verify_candidate_unchanged()
        manifest = _stage_view(
            self.candidate_root,
            self.root / VIEW_NAME,
            self.candidate_digest,
        )
        manifest_path = self.root / VIEW_MANIFEST_NAME
        manifest_path.write_bytes(_canonical(manifest.to_document()))
        manifest_path.chmod(0o444)
        self.input_digests[VIEW_MANIFEST_NAME] = _digest(manifest_path.read_bytes())
        self.view_manifest = manifest
        self.verify_inputs()
        return manifest


@dataclass(frozen=True)
class ProbeBundle:
    root: Path
    negative_declarations: tuple[dict[str, Any], ...]
    bundle_digest: str


@dataclass(frozen=True)
class EvidenceRow:
    requirement_id: str
    relation_digest: str
    document: dict[str, Any]


@dataclass(frozen=True)
class QualificationConfig:
    model: str = "gpt-5.6-luna"
    max_turns: int = 5
    command_timeout_seconds: float = 300.0
    turn_timeout_seconds: float = 600.0
    uv_cache_dir: Path = Path("/tmp/agent-env-foundry-qualification-uv-cache")

    def __post_init__(self) -> None:
        if (
            self.max_turns <= 0
            or self.command_timeout_seconds <= 0
            or self.turn_timeout_seconds <= 0
        ):
            raise ValueError("Qualification budgets must be positive")


@dataclass(frozen=True)
class QualificationResult:
    status: QualificationStatus
    candidate_digest: str
    expected_relations_digest: str
    evidence_digest: str | None = None
    evidence_rows: tuple[EvidenceRow, ...] = ()
    probe_bundle_digest: str | None = None
    negative_evidence_count: int = 0
    workspace_root: Path | None = None
    failure_code: str | None = None
    details: Mapping[str, Any] | None = None


def _canonical(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise QualificationFailure(
            "validation", "not_json_safe", "Value is not canonical JSON", error=str(exc)
        ) from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value))


def freeze_expected_relations(projection: BuilderProjection) -> ExpectedRelations:
    document = projection.to_document()
    source = [*document["requirements"], *document["initial_world_relations"]]
    frozen: list[ExpectedRelation] = []
    seen: set[str] = set()
    for position, raw in enumerate(source):
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise QualificationFailure(
                "expected_relations",
                "invalid_relation",
                f"Relation {position} needs a non-empty id",
            )
        requirement_id = cast(str, raw["id"])
        if requirement_id in seen:
            raise QualificationFailure(
                "expected_relations", "duplicate_relation", "Relation ids must be unique"
            )
        seen.add(requirement_id)
        frozen.append(
            ExpectedRelation(
                requirement_id, cast(dict[str, Any], _copy(raw)), _digest(_canonical(raw))
            )
        )
    preimage = {
        "relations": [
            {"requirement_id": item.requirement_id, "relation_digest": item.relation_digest}
            for item in frozen
        ]
    }
    return ExpectedRelations(tuple(frozen), _digest(_canonical(preimage)))


def prepare_qualification_workspace(
    projection: BuilderProjection,
    candidate_root: Path,
    candidate_digest: str,
    root: Path,
) -> PreparedQualificationWorkspace:
    workspace = Path(root)
    if workspace.is_symlink() or (workspace.exists() and any(workspace.iterdir())):
        raise QualificationFailure(
            "qualification_workspace",
            "workspace_not_fresh",
            "Qualification workspace must be fresh and empty",
        )
    workspace.mkdir(parents=True, exist_ok=True)
    expected = freeze_expected_relations(projection)
    expected_path = workspace / EXPECTED_NAME
    expected_path.write_bytes(_canonical(expected.to_document()))
    expected_path.chmod(0o444)
    candidate = Path(candidate_root).resolve()
    actual = compute_candidate_digest(candidate)
    if actual != candidate_digest:
        raise QualificationFailure(
            "candidate_integrity",
            "candidate_digest_mismatch",
            "Candidate digest differs before Qualification",
            expected_digest=candidate_digest,
            actual_digest=actual,
        )
    contract_path = workspace / CONTRACT_NAME
    shutil.copyfile(
        Path(__file__).parent / "runtime_skills/environment-codegen/ENVIRONMENT_CONTRACT.md",
        contract_path,
    )
    contract_path.chmod(0o444)
    inputs = {
        EXPECTED_NAME: _digest(expected_path.read_bytes()),
        CONTRACT_NAME: _digest(contract_path.read_bytes()),
    }
    prepared = PreparedQualificationWorkspace(
        workspace,
        candidate,
        candidate_digest,
        expected,
        inputs,
    )
    prepared.verify_inputs()
    prepared.verify_candidate_unchanged()
    return prepared


def validate_predicate_carrier(prepared: PreparedQualificationWorkspace) -> str:
    expected_members = {EXPECTED_NAME, CONTRACT_NAME, PREDICATE_NAME}
    actual_members = {path.name for path in prepared.root.iterdir()}
    if actual_members != expected_members:
        _fail(
            "predicate_gate",
            "predicate_output_invalid",
            "The candidate-blind turn must write exactly the predicate carrier",
            expected=sorted(expected_members),
            actual=sorted(actual_members),
        )
    path = prepared.root / PREDICATE_NAME
    if not path.is_file() or path.is_symlink():
        _fail(
            "predicate_gate",
            "predicate_output_invalid",
            "Predicate carrier must be one regular file",
        )
    raw = _read_json(path, "qualification predicates")
    required = {"format", "expected_relations_digest", "predicates"}
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or raw.get("format") != "qualification-predicates/1"
        or raw.get("expected_relations_digest") != prepared.expected.aggregate_digest
        or not isinstance(raw.get("predicates"), list)
    ):
        _fail(
            "predicate_gate",
            "predicate_output_invalid",
            "Predicate carrier header is invalid",
        )
    predicate_fields = {
        "requirement_id",
        "relation_digest",
        "predicate_id",
        "acceptance_predicate",
        "near_miss_intent",
    }
    predicates_by_requirement: dict[str, dict[str, Any]] = {}
    predicate_ids: set[str] = set()
    for position, item in enumerate(raw["predicates"]):
        if not isinstance(item, dict) or set(item) != predicate_fields:
            _fail(
                "predicate_gate",
                "predicate_output_invalid",
                f"Predicate {position} has invalid members",
            )
        requirement_id = item["requirement_id"]
        relation = prepared.expected.by_id.get(requirement_id)
        predicate_id = item["predicate_id"]
        if (
            relation is None
            or item["relation_digest"] != relation.relation_digest
            or requirement_id in predicates_by_requirement
            or not isinstance(predicate_id, str)
            or not predicate_id.strip()
            or predicate_id in predicate_ids
            or not _nonempty_prose(item["acceptance_predicate"])
            or not _nonempty_prose(item["near_miss_intent"])
        ):
            _fail(
                "predicate_gate",
                "predicate_output_invalid",
                f"Predicate {position} is not exactly bound to one expected relation",
            )
        predicates_by_requirement[requirement_id] = cast(dict[str, Any], _copy(item))
        predicate_ids.add(predicate_id)
    missing = set(prepared.expected.by_id) - set(predicates_by_requirement)
    if missing or len(predicates_by_requirement) != len(prepared.expected.relations):
        _fail(
            "predicate_gate",
            "predicate_relation_coverage",
            "Every expected relation needs exactly one predicate",
            missing=sorted(missing),
        )
    canonical_document = {
        "format": "qualification-predicates/1",
        "expected_relations_digest": prepared.expected.aggregate_digest,
        "predicates": [
            predicates_by_requirement[relation.requirement_id]
            for relation in prepared.expected.relations
        ],
    }
    canonical_bytes = _canonical(canonical_document)
    path.chmod(0o644)
    path.write_bytes(canonical_bytes)
    path.chmod(0o444)
    digest = _digest(canonical_bytes)
    prepared.predicate_digest = digest
    prepared.predicates = predicates_by_requirement
    prepared.input_digests[PREDICATE_NAME] = digest
    prepared.verify_host_inputs()
    return digest


def _nonempty_prose(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and any(character.isalpha() for character in value)
    )


def _stage_view(candidate: Path, destination: Path, candidate_digest: str) -> CandidateViewManifest:
    destination.mkdir()
    records: list[ViewFile] = []
    paths = sorted(candidate.rglob("*"), key=lambda item: item.relative_to(candidate).as_posix())
    for source in paths:
        relative = source.relative_to(candidate)
        if (
            any(part in _VIEW_EXCLUDED_PARTS for part in relative.parts)
            or source.is_symlink()
            or not source.is_file()
        ):
            continue
        if source.name in _VIEW_EXCLUDED_NAMES or not _view_allowed(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)
        records.append(ViewFile(relative.as_posix(), _digest(target.read_bytes())))
    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()), reverse=True
    ):
        directory.chmod(0o555)
    destination.chmod(0o555)
    preimage = {
        "candidate_digest": candidate_digest,
        "files": [{"path": item.path, "digest": item.digest} for item in records],
    }
    return CandidateViewManifest(candidate_digest, tuple(records), _digest(_canonical(preimage)))


def _view_allowed(relative: Path) -> bool:
    if len(relative.parts) == 1:
        return relative.name in _ROOT_PUBLIC or relative.name.startswith(("README", "LICENSE"))
    return relative.parts[0] in {"src", "docs"}


def _verify_readonly(path: Path, digest: str, role: str) -> None:
    actual = _digest(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    if actual != digest or mode != 0o444:
        raise QualificationFailure(
            "qualification_input",
            "qualification_input_modified",
            f"{role} changed after Host preparation",
            path=str(path),
            expected_digest=digest,
            actual_digest=actual,
            actual_mode=mode,
        )


def validate_probe_bundle(
    root: Path,
    expected: ExpectedRelations,
    predicates: Mapping[str, Mapping[str, Any]],
) -> ProbeBundle:
    workspace = Path(root)
    allowed = {
        EXPECTED_NAME,
        PREDICATE_NAME,
        VIEW_NAME,
        VIEW_MANIFEST_NAME,
        CONTRACT_NAME,
        *PROBE_SCRIPTS,
    }
    extras = {path.name for path in workspace.iterdir()} - allowed
    if extras:
        _fail(
            "probe_gate",
            "unexpected_probe_output",
            "Qualifier wrote files outside the bounded probe output",
            paths=sorted(extras),
        )
    forbidden_references: list[dict[str, str]] = []
    records: list[dict[str, str]] = []
    for name in PROBE_SCRIPTS:
        path = workspace / name
        if not path.is_file() or path.is_symlink():
            _fail(
                "probe_gate",
                "probe_file_missing",
                "Qualifier must author exactly the three disclosed Python probe files",
                missing=name,
            )
        records.append({"path": name, "digest": _digest(path.read_bytes())})
        forbidden_references.extend(
            _candidate_business_references(
                name,
                path.read_text(encoding="utf-8"),
            )
        )
    if forbidden_references:
        _fail(
            "probe_gate",
            "probe_source_forbidden",
            "Probe source bypasses candidate-business execution separation",
            violations=forbidden_references,
        )
    declarations: list[dict[str, Any]] = []
    for position, relation in enumerate(expected.relations, start=1):
        predicate = predicates.get(relation.requirement_id)
        if predicate is None:
            _fail(
                "probe_gate",
                "predicate_relation_coverage",
                "A Host-frozen predicate is missing for a controlled negative run",
                requirement_id=relation.requirement_id,
            )
        declarations.append(
            {
                "requirement_id": relation.requirement_id,
                "negative_run_id": f"negative-{position:03d}",
                "relation": _copy(relation.relation),
                "acceptance_predicate": predicate["acceptance_predicate"],
                "near_miss_intent": predicate["near_miss_intent"],
            }
        )
    preimage = {
        "format": "qualification-probes/2",
        "expected_relations_digest": expected.aggregate_digest,
        "files": records,
        "required_physical_checks": sorted(CHECK_CLASSES),
        "negative_declarations": declarations,
    }
    for name in PROBE_SCRIPTS:
        (workspace / name).chmod(0o444)
    manifest_path = workspace / PROBE_MANIFEST_NAME
    manifest_path.write_bytes(_canonical(preimage))
    manifest_path.chmod(0o444)
    return ProbeBundle(
        workspace,
        tuple(declarations),
        _digest(_canonical(preimage)),
    )


def _candidate_business_references(name: str, source: str) -> list[dict[str, str]]:
    normalized = source.lower().replace("\\", "/")
    markers = {
        "candidate-view": "candidate_view_runtime_access",
        "builder_projection.json": "candidate_private_input",
    }
    if name == "public_probe.py":
        markers.update(
            {
                "load_environment": "canonical_loader_bypass",
                "agent_env_foundry.environment": "canonical_loader_bypass",
            }
        )
    violations = [
        {"path": name, "reason": reason}
        for marker, reason in markers.items()
        if marker in normalized
    ]
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as exc:
        return [
            *violations,
            {"path": name, "reason": f"probe_syntax_invalid:{exc.lineno}:{exc.offset}"},
        ]
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    if "generated_environment" in imported:
        violations.append({"path": name, "reason": "candidate_business_import"})
    if "tests" in imported:
        violations.append({"path": name, "reason": "candidate_test_reference"})
    return violations


def validate_evidence_rows(
    rows: Any,
    expected: ExpectedRelations,
    journal: HostJournal,
) -> tuple[EvidenceRow, ...]:
    if not isinstance(rows, list):
        _fail("evidence", "evidence_invalid", "Evidence must be JSONL rows")
    required = {
        "requirement_id",
        "public_call_seqs",
        "native_observations",
        "assertions",
        "source_use",
    }
    ready: dict[str, EvidenceRow] = {}
    present: set[str] = set()
    covered_checks: set[str] = set()
    journal_calls = _journal_public_calls(journal)
    host_control_events = [
        event.to_document() for event in journal.events if event.operation != "invoke"
    ]
    issues: list[dict[str, Any]] = []

    def issue(
        code: str,
        message: str,
        *,
        requirement_id: Any = None,
        position: int | None = None,
        **details: Any,
    ) -> None:
        issues.append(
            {
                "code": code,
                "message": message,
                "requirement_id": requirement_id,
                "position": position,
                **details,
            }
        )

    for position, raw in enumerate(rows):
        issue_count = len(issues)
        try:
            document = cast(dict[str, Any], _copy(raw))
        except QualificationFailure as exc:
            issue("evidence_not_json", str(exc), position=position)
            continue
        if not isinstance(document, dict) or set(document) != required:
            issue(
                "evidence_invalid",
                "Evidence row members do not match the disclosed contract",
                position=position,
                expected_members=sorted(required),
                actual_members=sorted(document) if isinstance(document, dict) else None,
            )
            continue
        requirement_id = document["requirement_id"]
        relation = expected.by_id.get(requirement_id)
        if relation is None:
            issue(
                "unknown_relation",
                "Evidence names an unknown relation",
                requirement_id=requirement_id,
                position=position,
            )
            continue
        present.add(requirement_id)
        if requirement_id in ready:
            issue(
                "duplicate_relation",
                "Evidence contains the same relation more than once",
                requirement_id=requirement_id,
                position=position,
            )
            continue
        sequences = document["public_call_seqs"]
        if (
            not isinstance(sequences, list)
            or not sequences
            or any(
                not isinstance(sequence, int) or sequence not in journal_calls
                for sequence in sequences
            )
        ):
            issue(
                "public_call_missing",
                "Evidence must select real invoke sequence numbers from the Host journal",
                requirement_id=requirement_id,
                position=position,
                available_sequences=sorted(journal_calls),
                actual=sequences,
            )
            calls: list[dict[str, Any]] = []
        else:
            calls = [journal_calls[sequence] for sequence in sequences]
        if (
            not isinstance(document["native_observations"], list)
            or not document["native_observations"]
            or any(not isinstance(item, dict) for item in document["native_observations"])
        ):
            issue(
                "native_observation_missing",
                "A native fact is required",
                requirement_id=requirement_id,
                position=position,
                actual=document["native_observations"],
                expected="a non-empty list of structured native facts",
            )
        assertions = document["assertions"]
        if not isinstance(assertions, list) or not assertions:
            issue(
                "assertion_missing",
                "Assertions are required",
                requirement_id=requirement_id,
                position=position,
                actual=assertions,
                expected="a non-empty assertion list",
            )
            assertions = []
        assertion_ids: set[str] = set()
        for assertion in assertions:
            covers = assertion.get("covers") if isinstance(assertion, dict) else None
            if (
                not isinstance(assertion, dict)
                or not isinstance(assertion.get("assertion_id"), str)
                or not assertion["assertion_id"]
                or assertion.get("passed") is not True
                or "actual" not in assertion
                or "expected" not in assertion
                or not isinstance(covers, list)
                or not covers
                or any(item not in CHECK_CLASSES for item in covers)
            ):
                issue(
                    "assertion_failed",
                    "Assertion must pass and include actual/expected facts plus valid coverage",
                    requirement_id=requirement_id,
                    position=position,
                    actual=assertion,
                    expected={
                        "passed": True,
                        "covers": sorted(CHECK_CLASSES),
                        "required_fact_fields": ["actual", "expected"],
                    },
                    selected_public_calls=calls,
                    host_control_events=host_control_events,
                    allowed_covers=sorted(CHECK_CLASSES),
                )
                continue
            assertion_id = cast(str, assertion["assertion_id"])
            if assertion_id in assertion_ids:
                issue(
                    "assertion_duplicate",
                    "Assertion ids must be unique within one requirement",
                    requirement_id=requirement_id,
                    position=position,
                    assertion_id=assertion_id,
                )
                continue
            assertion_ids.add(assertion_id)
            covered_checks.update(cast(list[str], covers))
        if (
            calls
            and relation.relation.get("kind") == "refusals"
            and not _has_business_refusal(calls)
        ):
            issue(
                "business_refusal_missing",
                "Refusal evidence needs a non-contract business refusal",
                requirement_id=requirement_id,
                position=position,
                actual=calls,
            )
        if not isinstance(document["source_use"], dict):
            issue(
                "evidence_invalid",
                "source_use must be a structured object",
                requirement_id=requirement_id,
                position=position,
                actual=document["source_use"],
            )
        bound = {
            "requirement_id": requirement_id,
            "relation_digest": relation.relation_digest,
            "public_calls": calls,
            "native_observations": document["native_observations"],
            "assertions": assertions,
            "source_use": document["source_use"],
        }
        if len(issues) == issue_count:
            ready[requirement_id] = EvidenceRow(requirement_id, relation.relation_digest, bound)
    missing = set(expected.by_id) - present
    if missing:
        issue(
            "missing_relation_coverage",
            "Relations are uncovered",
            actual=sorted(present),
            expected=sorted(expected.by_id),
            missing=sorted(missing),
        )
    missing_checks = CHECK_CLASSES - covered_checks
    if missing_checks:
        issue(
            "missing_physical_check_coverage",
            "Semantic assertions do not cover every required physical obligation",
            actual=sorted(covered_checks),
            expected=sorted(CHECK_CLASSES),
            missing=sorted(missing_checks),
        )
    if issues:
        codes = {item["code"] for item in issues}
        _fail(
            "evidence",
            next(iter(codes)) if len(codes) == 1 else "evidence_semantic_failures",
            "Positive evidence has one or more semantic failures",
            issues=issues,
        )
    return tuple(ready[relation.requirement_id] for relation in expected.relations)


def _has_business_refusal(calls: Any) -> bool:
    for call in calls:
        observation = call.get("observation") if isinstance(call, dict) else None
        error = observation.get("error") if isinstance(observation, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if (
            isinstance(observation, dict)
            and observation.get("ok") is False
            and isinstance(code, str)
            and not code.startswith("contract.")
        ):
            return True
    return False


def _journal_public_calls(journal: HostJournal) -> dict[int, dict[str, Any]]:
    if not _is_host_journal(journal):
        raise QualificationFailure(
            "evidence",
            "host_journal_invalid",
            "Evidence authority requires a Host-created journal",
        )
    calls: dict[int, dict[str, Any]] = {}
    for event in journal.events:
        if event.operation != "invoke":
            continue
        arguments = event.arguments
        if isinstance(event.result, dict) and set(event.result) == {"host_exception"}:
            continue
        if not isinstance(event.result, dict) or set(event.result) != {"ok", "data", "error"}:
            raise QualificationFailure(
                "evidence", "host_journal_invalid", "Host invoke result is not canonical"
            )
        calls[event.seq] = {
            "seq": event.seq,
            "instance": event.instance,
            "tool_name": arguments["tool_name"],
            "arguments": arguments["arguments"],
            "observation": event.result,
        }
    return calls


def _require_host_outputs(
    outputs: Any,
) -> tuple[HostJournal, tuple[ControlledRunCarrier, ...]]:
    positive = outputs.get("positive_journal") if isinstance(outputs, dict) else None
    carriers = outputs.get("negative_carriers") if isinstance(outputs, dict) else None
    if not _is_host_journal(positive) or not isinstance(carriers, (list, tuple)):
        _fail(
            "evidence",
            "host_carrier_missing",
            "Probe execution lacks Host-created journal/carrier provenance",
        )
    if any(not _is_run_carrier(carrier) for carrier in carriers):
        _fail(
            "evidence",
            "host_carrier_missing",
            "Probe execution returned a non-Host carrier",
        )
    return cast(HostJournal, positive), cast(tuple[ControlledRunCarrier, ...], tuple(carriers))


def validate_negative_discrimination(
    bundle: ProbeBundle,
    negative_rows: Any,
    rows: tuple[EvidenceRow, ...],
    expected: ExpectedRelations,
    predicates: Mapping[str, Mapping[str, Any]],
    carriers: tuple[ControlledRunCarrier, ...],
    candidate_digest: str,
) -> tuple[dict[str, Any], ...]:
    declarations = {
        item.get("requirement_id"): item
        for item in bundle.negative_declarations
        if isinstance(item, dict)
    }
    missing = set(expected.by_id) - set(declarations)
    if missing or len(declarations) != len(bundle.negative_declarations):
        _fail(
            "negative",
            "missing_negative_relation_coverage",
            "Every frozen relation needs one negative discrimination row",
            missing=sorted(missing),
        )
    carrier_by_run = {carrier.run_id: carrier for carrier in carriers}
    required_runs = {item["negative_run_id"] for item in declarations.values()}
    if set(carrier_by_run) != required_runs or len(carrier_by_run) != len(carriers):
        _fail(
            "negative",
            "negative_run_carrier_missing",
            "Every declared negative run needs exactly one Host carrier",
            missing=sorted(required_runs - set(carrier_by_run)),
        )
    noop_runs: list[str] = []
    unbound_runs: list[str] = []
    for carrier in carriers:
        if not _existing_release_file_changed(carrier.release_before, carrier.release_after):
            noop_runs.append(carrier.run_id)
        if (
            carrier.original_candidate_digest != candidate_digest
            or carrier.executed_copy_digest != carrier.release_after.digest
            or _tree_manifest(carrier.release_root).digest != carrier.executed_copy_digest
        ):
            unbound_runs.append(carrier.run_id)
    if noop_runs:
        _fail(
            "negative",
            "negative_physical_noop",
            "Near misses must change existing release files; added markers do not count",
            run_ids=noop_runs,
            actual="no pre-existing release file changed in each listed run",
            expected="at least one pre-existing release file digest or mode changes per run",
        )
    if unbound_runs:
        _fail(
            "negative",
            "negative_source_copy_unbound",
            "Executed copies are not mechanically bound to their Host carriers",
            run_ids=unbound_runs,
        )
    if not isinstance(negative_rows, list):
        _fail("negative", "negative_evidence_invalid", "Negative evidence must be JSONL rows")
    negatives = {
        item.get("requirement_id"): item for item in negative_rows if isinstance(item, dict)
    }
    if set(negatives) != set(expected.by_id) or len(negatives) != len(negative_rows):
        _fail(
            "negative",
            "missing_negative_relation_coverage",
            "Negative evidence does not cover every frozen relation exactly once",
        )
    model_fields = {
        "requirement_id",
        "public_call_seqs",
        "native_observations",
        "assertions",
        "source_use",
    }
    issues: list[dict[str, Any]] = []
    ready: dict[str, dict[str, Any]] = {}

    def issue(requirement_id: str, code: str, message: str, **details: Any) -> None:
        issues.append(
            {
                "requirement_id": requirement_id,
                "code": code,
                "message": message,
                **details,
            }
        )

    for relation in expected.relations:
        issue_count = len(issues)
        declaration = declarations[relation.requirement_id]
        negative = negatives[relation.requirement_id]
        predicate = predicates.get(relation.requirement_id)
        if set(negative) != model_fields or predicate is None:
            issue(
                relation.requirement_id,
                "negative_relation_mismatch",
                "Negative evidence does not match the disclosed semantic row contract",
                expected_members=sorted(model_fields),
                actual_members=sorted(negative) if isinstance(negative, dict) else None,
            )
            continue
        baseline = next(
            (row for row in rows if row.requirement_id == relation.requirement_id),
            None,
        )
        if baseline is None:
            issue(
                relation.requirement_id,
                "negative_assertion_mismatch",
                "The corresponding positive evidence row is missing",
            )
            continue
        baseline_assertion_rows = baseline.document["assertions"] if baseline is not None else []
        baseline_assertions = {
            cast(str, item["assertion_id"]): item
            for item in baseline_assertion_rows
            if isinstance(item, dict)
            and item.get("passed") is True
            and isinstance(item.get("assertion_id"), str)
        }
        negative_assertions = negative["assertions"]
        if not isinstance(negative_assertions, list) or not negative_assertions:
            issue(
                relation.requirement_id,
                "negative_evidence_invalid",
                "Negative assertions must be a non-empty list",
            )
            continue
        negative_by_id: dict[str, dict[str, Any]] = {}
        assertions_valid = True
        for item in negative_assertions:
            covers = item.get("covers") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("assertion_id"), str)
                or not item["assertion_id"]
                or not isinstance(item.get("passed"), bool)
                or "actual" not in item
                or "expected" not in item
                or not isinstance(covers, list)
                or not covers
                or any(check not in CHECK_CLASSES for check in covers)
                or item["assertion_id"] in negative_by_id
            ):
                issue(
                    relation.requirement_id,
                    "negative_evidence_invalid",
                    "Negative assertions need unique ids, actual/expected facts, "
                    "and valid coverage",
                )
                assertions_valid = False
                break
            negative_by_id[cast(str, item["assertion_id"])] = item
        if not assertions_valid:
            continue
        matching_flips = [
            assertion_id
            for assertion_id, negative_assertion in negative_by_id.items()
            if negative_assertion["passed"] is False
            and assertion_id in baseline_assertions
            and _canonical(negative_assertion["expected"])
            == _canonical(baseline_assertions[assertion_id]["expected"])
            and set(cast(list[str], negative_assertion["covers"]))
            == set(cast(list[str], baseline_assertions[assertion_id]["covers"]))
        ]
        if not matching_flips:
            issue(
                relation.requirement_id,
                "negative_assertion_mismatch",
                "A controlled near miss must flip the same assertion, expected fact, and coverage",
                baseline_assertions=sorted(baseline_assertions),
                negative_false_assertions=sorted(
                    assertion_id
                    for assertion_id, item in negative_by_id.items()
                    if item["passed"] is False
                ),
                actual=negative_assertions,
                expected={
                    "matching_assertion_ids": sorted(baseline_assertions),
                    "passed": False,
                    "same_expected_and_covers": True,
                },
            )
        carrier = carrier_by_run[declaration["negative_run_id"]]
        journal_calls = _journal_public_calls(carrier.journal)
        sequences = negative["public_call_seqs"]
        if (
            not isinstance(sequences, list)
            or not sequences
            or any(
                not isinstance(sequence, int) or sequence not in journal_calls
                for sequence in sequences
            )
        ):
            issue(
                relation.requirement_id,
                "negative_call_not_in_journal",
                "Negative evidence must select real invoke sequences from its exact Host journal",
                available_sequences=sorted(journal_calls),
                actual=sequences,
            )
            calls: list[dict[str, Any]] = []
        else:
            calls = [journal_calls[sequence] for sequence in sequences]
            if not _public_behavior_changed(baseline.document["public_calls"], calls):
                issue(
                    relation.requirement_id,
                    "negative_public_behavior_unchanged",
                    "The near miss changed no observation for a matching public call",
                    actual="matching tool-name/arguments calls returned identical observations",
                    expected="at least one matching public call returns a different observation",
                )
        native = negative["native_observations"]
        if (
            not isinstance(native, list)
            or not native
            or any(not isinstance(item, dict) for item in native)
        ):
            issue(
                relation.requirement_id,
                "native_observation_missing",
                "Negative native evidence is required",
            )
        if not isinstance(negative["source_use"], dict):
            issue(
                relation.requirement_id,
                "negative_evidence_invalid",
                "source_use must be an object",
            )
        if len(issues) == issue_count:
            ready[relation.requirement_id] = {
                "requirement_id": relation.requirement_id,
                "relation_digest": relation.relation_digest,
                "predicate_id": predicate["predicate_id"],
                "negative_run_id": declaration["negative_run_id"],
                "public_calls": calls,
                "native_observations": native,
                "assertions": negative_assertions,
                "source_use": negative["source_use"],
            }
    if issues:
        codes = {item["code"] for item in issues}
        _fail(
            "negative",
            next(iter(codes)) if len(codes) == 1 else "negative_semantic_failures",
            "Controlled negative evidence has one or more semantic failures",
            issues=issues,
        )
    validated = [ready[relation.requirement_id] for relation in expected.relations]
    return tuple(validated)


def _existing_release_file_changed(before: TreeManifest, after: TreeManifest) -> bool:
    after_by_path = {record.path: record for record in after.records}
    return any(
        record.object_type == "file"
        and (updated := after_by_path.get(record.path)) is not None
        and updated.object_type == "file"
        and (updated.digest != record.digest or updated.mode != record.mode)
        for record in before.records
    )


def _public_behavior_changed(
    baseline_calls: list[dict[str, Any]], negative_calls: list[dict[str, Any]]
) -> bool:
    baseline = {
        _canonical({"tool_name": call["tool_name"], "arguments": call["arguments"]}): _canonical(
            call["observation"]
        )
        for call in baseline_calls
    }
    return any(
        (key := _canonical({"tool_name": call["tool_name"], "arguments": call["arguments"]}))
        in baseline
        and baseline[key] != _canonical(call["observation"])
        for call in negative_calls
    )


_BASE_INSTRUCTIONS = (
    "Independently qualify EXPECTED_RELATIONS.json against ENVIRONMENT_CONTRACT.md. "
    "The Host has already authored and frozen QUALIFICATION_PREDICATES.json before this "
    "coding thread began, then staged candidate-view. Never rewrite those inputs. "
    "Candidate source is read only to locate or decode native representation. The Host, "
    "not probe code, executes public calls through a private runner and owns canonical "
    "journals. Do not issue a terminal verdict."
)

_PREDICATE_PROMPT = (
    "Without candidate source or tools, author one natural-language acceptance predicate "
    "and one reachable near-miss intent for every supplied relation, in the exact supplied "
    "order. Return only those two semantic fields per item; do not copy or invent IDs, "
    "digests, carrier headers, implementation names, storage layout, Tasks, rewards, or "
    "a terminal verdict. The Host binds every item to its frozen relation."
)

_PREDICATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "predicates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "acceptance_predicate": {"type": "string"},
                    "near_miss_intent": {"type": "string"},
                },
                "required": [
                    "acceptance_predicate",
                    "near_miss_intent",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["predicates"],
    "additionalProperties": False,
}

_PROBE_PROMPT = (
    "The Host has frozen QUALIFICATION_PREDICATES.json and staged candidate-view. Write "
    "exactly three ordinary Python programs: public_probe.py, negative_setup.py, and "
    "native_probe.py. Write no manifest, digest, relation binding, journal copy, verdict, "
    "Task, or reward artifact; the Host deterministically owns all of those. "
    "public_probe.py defines run(session, mode). The Host imports and calls that function. "
    "Use only session.open(instance_name), then reset/tools/invoke/close on the returned "
    "environment. Exercise real multi-step value chaining, business refusals, repeated "
    "non-null starts, reset reconstruction, instance isolation, and reload persistence. "
    "The Host records every call; public_probe.py must not write evidence or inspect native "
    "paths. mode is baseline or negative; the negative mode exercises the same relevant "
    "public behavior against one Host-controlled near-miss release. "
    "For refusal/no-mutation checks, compare native/public state immediately before and "
    "after the refused call or use a separate named refusal instance. Do not require a "
    "global final count of zero when earlier valid calls intentionally created state. "
    "negative_setup.py is an argv program with a __main__ entry point. argv[1:4] are exactly "
    "release_root, instance_root, declarations_path. declarations_path is the path of a "
    "JSON file that must be read; its document is a list containing one Host-bound object "
    "with requirement_id, negative_run_id, relation, "
    "acceptance_predicate, and near_miss_intent. Apply a reachable semantic near miss only "
    "beneath the supplied release/instance roots by modifying a real file that already "
    "exists in release_root. Adding a marker, metadata, declaration, or unrelated file does "
    "not count. The mutation must make at least one public call with the same tool name and "
    "arguments as baseline return a different observation. "
    "native_probe.py is an argv program with a __main__ entry point. argv[1:4] are exactly "
    "runtime_root, evidence_jsonl, negative_evidence_jsonl. Use an independent standard "
    "reader appropriate to the candidate representation and never import candidate "
    "business code or Builder tests. The runtime contains baseline-instances, "
    "baseline.journal.jsonl, and negative-runs/<negative_run_id>/{release,instances,"
    "declarations.json,journal.jsonl}. Host journal rows contain run_id, seq, instance, "
    "operation, arguments, and result. "
    "For native paths, the positive instance root is runtime_root/baseline-instances and a "
    "negative instance root is runtime_root/negative-runs/<negative_run_id>/instances; do "
    "not append an extra instances segment to either root. "
    "When several named instance directories exist, select the instance that owns the "
    "public calls being verified; never use an ambiguous first/next recursive database match. "
    "A successful ToolObservation has error=null and a refusal has data=null. Handle these "
    "nullable fields explicitly; for example use (observation.get('error') or {}).get('code'), "
    "never chain .get after observation.get('error', {}). "
    "Write exactly one positive and one negative JSONL row per requirement. Every row has "
    "exactly requirement_id, public_call_seqs, native_observations, assertions, and "
    "source_use. public_call_seqs selects real invoke seq integers from that run's Host "
    "journal; do not copy calls. native_observations is a non-empty list of structured "
    "facts. assertions is a non-empty list of objects with assertion_id, passed, covers, "
    "and useful actual/expected facts. covers contains one or more of "
    "reset_reconstruction, value_chain, native_before_after, refusal_no_mutation, "
    "instance_isolation, nondefault_start_repeat, reload_persistence; the complete positive "
    "suite must cover all seven. Positive assertions must be computed from real public "
    "and native observations and pass. The matching controlled near miss must make at least "
    "one identical assertion_id with the same expected fact and covers list false. Literal "
    "or unconditional True/False evidence is "
    "forbidden; derive the false result from the changed public/native behavior, never from "
    "a marker or declaration file. Each negative row must read the matching "
    "negative-runs directory selected by its declarations.json; never reuse one run for all "
    "requirements. source_use is a structured object describing any source read solely to "
    "decode native state. Once the three programs are complete, end the turn immediately "
    "without additional analysis or narrative."
)


def run_qualification(
    projection: BuilderProjection,
    candidate_root: Path,
    candidate_digest: str,
    workspace_root: Path,
    *,
    config: QualificationConfig,
) -> QualificationResult:
    expected = freeze_expected_relations(projection)
    try:
        prepared = prepare_qualification_workspace(
            projection, candidate_root, candidate_digest, workspace_root
        )
        bundle, rows, negative, carriers = _author_probes(prepared, config)
        prepared.verify_inputs()
        prepared.verify_candidate_unchanged()
        preimage = {
            "candidate_digest": prepared.candidate_digest,
            "expected_relations_digest": expected.aggregate_digest,
            "probe_bundle_digest": bundle.bundle_digest,
            "rows": [row.document for row in rows],
            "negative_rows": list(negative),
            "negative_carriers": [carrier.to_document() for carrier in carriers],
        }
        return QualificationResult(
            status="passed",
            candidate_digest=candidate_digest,
            expected_relations_digest=expected.aggregate_digest,
            evidence_digest=_digest(_canonical(preimage)),
            evidence_rows=rows,
            probe_bundle_digest=bundle.bundle_digest,
            negative_evidence_count=len(negative),
            workspace_root=prepared.root,
        )
    except QualificationFailure as exc:
        status: QualificationStatus = (
            "candidate_defect"
            if exc.code in _CANDIDATE_FAILURE_CODES
            else "infra_failure"
            if exc.phase in {"provider", "infrastructure"}
            else "probe_defect"
        )
        return QualificationResult(
            status=status,
            candidate_digest=candidate_digest,
            expected_relations_digest=expected.aggregate_digest,
            workspace_root=Path(workspace_root),
            failure_code=exc.code,
            details={"message": str(exc), **exc.details},
        )
    except Exception as exc:
        return QualificationResult(
            status="infra_failure",
            candidate_digest=candidate_digest,
            expected_relations_digest=expected.aggregate_digest,
            workspace_root=Path(workspace_root),
            failure_code="qualifier_sdk_failed",
            details={"error_type": type(exc).__name__, "message": str(exc)},
        )


def _author_predicates(
    prepared: PreparedQualificationWorkspace,
    config: QualificationConfig,
) -> str:
    provider_input = {
        "relations": [_copy(relation.relation) for relation in prepared.expected.relations]
    }
    try:
        document = _run_fresh_json_turn(
            route=AgentRoute(model=config.model, max_provider_turns=2),
            client_factory=_default_client_factory,
            instructions=_PREDICATE_PROMPT,
            input_text=json.dumps(provider_input, ensure_ascii=False, sort_keys=True),
            schema_name="qualification_predicates",
            schema=_PREDICATE_SCHEMA,
            provider_budget=_ProviderTurnBudget(2),
        )
    except ResearchFailure as exc:
        raise QualificationFailure(
            "provider",
            "predicate_provider_failed",
            "Candidate-blind predicate generation failed",
            original_code=exc.code,
            original_message=str(exc),
            **exc.details,
        ) from exc
    drafts = document.get("predicates")
    if not isinstance(drafts, list) or len(drafts) != len(prepared.expected.relations):
        raise QualificationFailure(
            "predicate_gate",
            "predicate_output_invalid",
            "Predicate draft count does not match the frozen relations",
            expected=len(prepared.expected.relations),
            actual=len(drafts) if isinstance(drafts, list) else None,
        )
    predicates: list[dict[str, Any]] = []
    for position, (relation, draft) in enumerate(
        zip(prepared.expected.relations, drafts, strict=True), start=1
    ):
        if (
            not isinstance(draft, dict)
            or set(draft) != {"acceptance_predicate", "near_miss_intent"}
            or not _nonempty_prose(draft["acceptance_predicate"])
            or not _nonempty_prose(draft["near_miss_intent"])
        ):
            raise QualificationFailure(
                "predicate_gate",
                "predicate_output_invalid",
                f"Predicate draft {position - 1} has invalid semantic fields",
            )
        predicates.append(
            {
                "requirement_id": relation.requirement_id,
                "relation_digest": relation.relation_digest,
                "predicate_id": f"predicate-{position:03d}",
                "acceptance_predicate": draft["acceptance_predicate"],
                "near_miss_intent": draft["near_miss_intent"],
            }
        )
    carrier = {
        "format": "qualification-predicates/1",
        "expected_relations_digest": prepared.expected.aggregate_digest,
        "predicates": predicates,
    }
    path = prepared.root / PREDICATE_NAME
    path.write_bytes(_canonical(carrier))
    return validate_predicate_carrier(prepared)


def _run_codex_turn(thread: Any, prompt: str, timeout_seconds: float) -> Any:
    if not hasattr(thread, "turn"):
        return thread.run(prompt)
    handle = thread.turn(prompt)
    completed = threading.Event()
    outcome: dict[str, Any] = {}

    def consume() -> None:
        try:
            outcome["result"] = handle.run()
        except BaseException as exc:  # surfaced unchanged in the calling thread
            outcome["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=consume, name="qualification-codex-turn", daemon=True)
    worker.start()
    if not completed.wait(timeout_seconds):
        try:
            handle.interrupt()
        except Exception as exc:
            outcome["interrupt_error"] = f"{type(exc).__name__}: {exc}"
        completed.wait(10.0)
        raise QualificationFailure(
            "infrastructure",
            "qualifier_turn_timeout",
            "Codex probe-authoring turn exceeded its bounded timeout",
            timeout_seconds=timeout_seconds,
            interrupt_error=outcome.get("interrupt_error"),
        )
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("result")


def _author_probes(
    prepared: PreparedQualificationWorkspace, config: QualificationConfig
) -> tuple[
    ProbeBundle,
    tuple[EvidenceRow, ...],
    tuple[dict[str, Any], ...],
    tuple[ControlledRunCarrier, ...],
]:
    previous: str | None = None
    _author_predicates(prepared, config)
    prepared.stage_candidate_view()
    with tempfile.TemporaryDirectory(
        prefix="agent-env-foundry-qualifier-home-",
        dir=prepared.root.parent,
        ignore_cleanup_errors=True,
    ) as codex_home:
        sdk_config = CodexConfig(
            cwd=str(prepared.root),
            env={"CODEX_HOME": codex_home, "UV_CACHE_DIR": str(config.uv_cache_dir)},
            config_overrides=_provider_overrides(),
        )
        with Codex(sdk_config) as codex:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                base_instructions=_BASE_INSTRUCTIONS,
                cwd=str(prepared.root),
                model=config.model,
                sandbox=Sandbox.workspace_write,
            )
            prompt = _PROBE_PROMPT
            for turn in range(config.max_turns):
                _run_codex_turn(thread, prompt, config.turn_timeout_seconds)
                prepared.verify_inputs()
                prepared.verify_candidate_unchanged()
                bundle: ProbeBundle | None = None
                try:
                    bundle = validate_probe_bundle(
                        prepared.root, prepared.expected, prepared.predicates
                    )
                    outputs = _execute_probes(prepared, bundle, config)
                    positive_journal, carriers = _require_host_outputs(outputs)
                    rows = validate_evidence_rows(
                        outputs["rows"], prepared.expected, positive_journal
                    )
                    negative = validate_negative_discrimination(
                        bundle,
                        outputs["negative_rows"],
                        rows,
                        prepared.expected,
                        prepared.predicates,
                        carriers,
                        prepared.candidate_digest,
                    )
                    return bundle, rows, negative, carriers
                except QualificationFailure as exc:
                    if exc.code in _CANDIDATE_FAILURE_CODES or exc.phase in {
                        "candidate_execution",
                        "provider",
                        "infrastructure",
                    }:
                        raise
                    current = _probe_digest(prepared.root)
                    facts = {"code": exc.code, "message": str(exc), "details": exc.details}
                    if previous == current:
                        raise QualificationFailure(
                            "probe_gate",
                            "qualifier_stalled",
                            "Qualifier changed no probe bytes after feedback",
                            prior_failure=facts,
                        ) from exc
                    previous = current
                    if turn + 1 == config.max_turns:
                        raise
                    _reset_probe_attempt(prepared.root, admitted=bundle is not None)
                    prompt = _render_probe_feedback(exc)
    raise QualificationFailure("probe_gate", "probe_bundle_missing", "Qualifier produced no probes")


def _reset_probe_attempt(root: Path, *, admitted: bool) -> None:
    if not admitted:
        return
    runtime = root / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    manifest = root / PROBE_MANIFEST_NAME
    if manifest.exists():
        manifest.unlink()
    for name in PROBE_SCRIPTS:
        path = root / name
        if path.is_file() and not path.is_symlink():
            path.chmod(0o644)


def _render_probe_feedback(exc: QualificationFailure) -> str:
    findings = json.dumps(exc.details, ensure_ascii=False, sort_keys=True, indent=2)
    return (
        "REJECTED\n"
        f"phase: {exc.phase}\ncode: {exc.code}\nmessage: {exc}\n\n"
        "ALL_FINDINGS\n"
        f"{findings}\n\n"
        "REPAIR\n"
        "Edit the existing public_probe.py, negative_setup.py, and native_probe.py in "
        "place. Fix every listed finding in this one turn, not only the first item. Treat "
        "actual and expected values as decisive. Preserve behavior that already passed. "
        "Recheck all frozen requirements, all matching negative-run directories, all three "
        "argv/function interfaces, and all seven physical obligations. Do not write Host "
        "metadata, probe_manifest.json, copied journals, verdicts, Tasks, or rewards.\n\n"
        "RESUBMIT\n"
        "When all three complete programs are corrected, end the turn immediately without "
        "an explanation or Markdown response."
    )


def _provider_overrides() -> tuple[str, ...]:
    base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not base or not os.environ.get("OPENAI_API_KEY"):
        raise QualificationFailure(
            "provider", "provider_configuration_missing", "Explicit provider route/key required"
        )
    provider = "foundry_qualification"
    return (
        f'model_provider="{provider}"',
        f'model_providers.{provider}.name="Foundry Qualification"',
        f"model_providers.{provider}.base_url={json.dumps(base)}",
        f'model_providers.{provider}.env_key="OPENAI_API_KEY"',
        f'model_providers.{provider}.wire_api="responses"',
        f"model_providers.{provider}.supports_websockets=true",
    )


def _probe_digest(root: Path) -> str:
    records = [
        {
            "path": name,
            "digest": _digest((root / name).read_bytes()) if (root / name).is_file() else None,
        }
        for name in (*PROBE_SCRIPTS, PROBE_MANIFEST_NAME)
    ]
    return _digest(_canonical({"files": records}))


def _verify_probe_bundle_unchanged(bundle: ProbeBundle) -> None:
    manifest = _read_json(bundle.root / PROBE_MANIFEST_NAME, "Host probe manifest")
    actual_bundle_digest = _digest(_canonical(manifest))
    if actual_bundle_digest != bundle.bundle_digest:
        raise QualificationFailure(
            "probe_integrity",
            "probe_manifest_changed",
            "The Host-compiled probe manifest changed after admission",
            expected_digest=bundle.bundle_digest,
            actual_digest=actual_bundle_digest,
        )
    records = manifest.get("files") if isinstance(manifest, dict) else None
    actual_records = [
        {
            "path": name,
            "digest": _digest((bundle.root / name).read_bytes())
            if (bundle.root / name).is_file() and not (bundle.root / name).is_symlink()
            else None,
        }
        for name in PROBE_SCRIPTS
    ]
    if records != actual_records:
        raise QualificationFailure(
            "probe_integrity",
            "probe_source_changed",
            "Admitted probe code changed before or during execution",
            expected=records,
            actual=actual_records,
        )


def _execute_probes(
    prepared: PreparedQualificationWorkspace, bundle: ProbeBundle, config: QualificationConfig
) -> dict[str, Any]:
    _verify_probe_bundle_unchanged(bundle)
    runtime = prepared.root / "runtime"
    dependencies = runtime / "loader-deps"
    runtime.mkdir()
    candidate_python = prepared.candidate_root / ".venv/bin/python"
    if not candidate_python.is_file():
        raise QualificationFailure(
            "probe_execution", "candidate_python_missing", "Candidate .venv Python is missing"
        )
    env = _clean_env(config)
    _run(
        (
            "uv",
            "pip",
            "install",
            "--offline",
            "--link-mode",
            "copy",
            "--python",
            str(candidate_python),
            "--target",
            str(dependencies),
            "rfc8785",
            "jsonschema",
        ),
        prepared.root,
        env,
        config,
        "loader_dependency_install",
    )
    baseline_instances = runtime / "baseline-instances"
    baseline_instances.mkdir()
    baseline_journal_path = runtime / "baseline.journal.jsonl"
    positive_journal = _execute_public_probe(
        candidate_python,
        prepared.candidate_root,
        baseline_instances,
        f"baseline-{uuid.uuid4().hex}",
        baseline_journal_path,
        "baseline",
        bundle,
        dependencies,
        env,
        config,
    )
    prepared.verify_candidate_unchanged()
    carriers: list[ControlledRunCarrier] = []
    declarations = bundle.negative_declarations
    for run_id in sorted({item["negative_run_id"] for item in declarations}):
        run_root = runtime / "negative-runs" / run_id
        release_root = run_root / "release"
        instance_root = run_root / "instances"
        try:
            _copy_release(prepared.candidate_root, release_root)
        except Exception as exc:
            raise QualificationFailure(
                "candidate_execution",
                "candidate_release_invalid",
                "Candidate release could not be copied and verified for a controlled run",
                run_id=run_id,
                error=f"{type(exc).__name__}: {exc}",
            ) from exc
        instance_root.mkdir()
        release_before = _tree_manifest(release_root)
        instance_before = _tree_manifest(instance_root)
        subset = [item for item in declarations if item["negative_run_id"] == run_id]
        declarations_path = run_root / "declarations.json"
        declarations_path.write_bytes(_canonical(subset))
        declarations_path.chmod(0o444)
        _run(
            (
                sys.executable,
                "-I",
                str(bundle.root / "negative_setup.py"),
                str(release_root),
                str(instance_root),
                str(declarations_path),
            ),
            run_root,
            env,
            config,
            f"negative_setup:{run_id}",
        )
        release_after = _tree_manifest(release_root)
        instance_after = _tree_manifest(instance_root)
        if release_after.digest != release_before.digest:
            try:
                release_after = _rebind_release_copy(release_root)
            except Exception as exc:
                raise QualificationFailure(
                    "probe_execution",
                    "negative_release_rebind_failed",
                    "Qualifier source mutation could not be rebound as a valid release copy",
                    run_id=run_id,
                    error=f"{type(exc).__name__}: {exc}",
                ) from exc
        prepared.verify_candidate_unchanged()
        journal_path = run_root / "journal.jsonl"
        journal = _execute_public_probe(
            candidate_python,
            release_root,
            instance_root,
            run_id,
            journal_path,
            "negative",
            bundle,
            dependencies,
            env,
            config,
        )
        prepared.verify_candidate_unchanged()
        carriers.append(
            _make_run_carrier(
                run_id,
                release_root,
                instance_root,
                release_before,
                release_after,
                instance_before,
                instance_after,
                journal,
                prepared.candidate_digest,
            )
        )
    evidence_path = runtime / "evidence.jsonl"
    negative_evidence_path = runtime / "negative-evidence.jsonl"
    snapshots = [(baseline_instances, _tree_manifest(baseline_instances))]
    snapshots.extend(
        (root, _tree_manifest(root))
        for carrier in carriers
        for root in (carrier.release_root, carrier.instance_root)
    )
    _run(
        (
            sys.executable,
            "-I",
            str(bundle.root / "native_probe.py"),
            str(runtime),
            str(evidence_path),
            str(negative_evidence_path),
        ),
        prepared.root,
        env,
        config,
        "native_probe",
    )
    _verify_execution_journal(baseline_journal_path, positive_journal)
    for carrier in carriers:
        _verify_execution_journal(carrier.release_root.parent / "journal.jsonl", carrier.journal)
    _verify_native_reader_immutability(snapshots)
    _verify_probe_bundle_unchanged(bundle)
    prepared.verify_candidate_unchanged()
    return {
        "positive_journal": positive_journal,
        "negative_carriers": tuple(carriers),
        "rows": _read_jsonl(evidence_path),
        "negative_rows": _read_jsonl(negative_evidence_path),
    }


def _execute_public_probe(
    python: Path,
    release: Path,
    instances: Path,
    run_id: str,
    journal_path: Path,
    mode: str,
    bundle: ProbeBundle,
    dependencies: Path,
    env: dict[str, str],
    config: QualificationConfig,
) -> HostJournal:
    public_env = {
        **env,
        "AGENT_ENV_FOUNDRY_JOURNAL": str(journal_path),
        "AGENT_ENV_FOUNDRY_RUN_ID": run_id,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            (
                str(release / "src"),
                str(Path(__file__).resolve().parents[1]),
                str(dependencies),
            )
        ),
    }
    _run(
        (
            str(python),
            "-B",
            "-m",
            "agent_env_foundry._qualification_runner",
            "--probe",
            str(bundle.root / "public_probe.py"),
            "--release",
            str(release),
            "--instances",
            str(instances),
            "--mode",
            mode,
        ),
        bundle.root,
        public_env,
        config,
        f"public_probe:{run_id}",
    )
    return _load_execution_journal(journal_path, run_id)


def _load_execution_journal(path: Path, run_id: str) -> HostJournal:
    try:
        journal = _load_host_journal(path, run_id)
        path.chmod(0o444)
    except (OSError, ValueError) as exc:
        raise QualificationFailure(
            "probe_output",
            "host_journal_invalid",
            "Private runner did not produce a valid Host journal",
            path=str(path),
            error=str(exc),
        ) from exc
    return journal


def _verify_execution_journal(path: Path, expected: HostJournal) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    try:
        actual = _load_host_journal(path, expected.run_id)
    except ValueError as exc:
        raise QualificationFailure(
            "probe_output",
            "host_journal_modified",
            "A sealed Host journal changed during native inspection",
            path=str(path),
            error=str(exc),
        ) from exc
    if mode != 0o444 or actual.digest != expected.digest:
        raise QualificationFailure(
            "probe_output",
            "host_journal_modified",
            "A sealed Host journal changed during native inspection",
            path=str(path),
            expected_digest=expected.digest,
            actual_digest=actual.digest,
            actual_mode=mode,
        )


def _verify_native_reader_immutability(
    snapshots: list[tuple[Path, TreeManifest]],
) -> None:
    for root, before in snapshots:
        after = _tree_manifest(root)
        if after.digest != before.digest:
            raise QualificationFailure(
                "probe_output",
                "native_reader_mutated_state",
                "Native-reader execution changed a controlled instance root",
                root=str(root),
                before_digest=before.digest,
                after_digest=after.digest,
            )


def _clean_env(config: QualificationConfig) -> dict[str, str]:
    env = dict(os.environ)
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env["UV_CACHE_DIR"] = str(config.uv_cache_dir)
    return env


def _run(
    command: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    config: QualificationConfig,
    phase: str,
) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=config.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationFailure(
            "infrastructure",
            "probe_process_failed",
            f"{phase} could not run",
            error=f"{type(exc).__name__}: {exc}",
        ) from exc
    if result.returncode:
        if phase == "loader_dependency_install":
            raise QualificationFailure(
                "infrastructure",
                "loader_dependency_unavailable",
                "Locked loader dependencies are unavailable in the local uv cache",
                command=list(command),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if phase.startswith("public_probe:") and result.returncode == 20:
            if not phase.startswith("public_probe:baseline-"):
                raise QualificationFailure(
                    "probe_execution",
                    "negative_public_runtime_failed",
                    f"{phase} made the controlled near-miss release violate the base contract",
                    command=list(command),
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    actual="the mutated release raised a canonical environment runtime failure",
                    expected="a loadable release with reachable but semantically wrong behavior",
                )
            raise QualificationFailure(
                "candidate_execution",
                "candidate_runtime_failed",
                f"{phase} observed a canonical environment failure",
                command=list(command),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        raise QualificationFailure(
            "probe_execution",
            "probe_execution_failed",
            f"{phase} exited {result.returncode}",
            command=list(command),
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _read_json(path: Path, role: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationFailure(
            "probe_output",
            "probe_output_invalid",
            f"Cannot read {role}",
            path=str(path),
            error=str(exc),
        ) from exc


def _read_jsonl(path: Path) -> list[Any]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationFailure(
            "probe_output",
            "probe_output_invalid",
            "Cannot read evidence JSONL",
            path=str(path),
            error=str(exc),
        ) from exc

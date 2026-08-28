"""Mechanical rejection evidence for the independent Slice 4 harness.

These fixtures exercise Host ordering and validation only.  They are not a
hand-authored environment and cannot produce a successful Qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import agent_env_foundry._qualification_runner as runner_module
import agent_env_foundry.qualification as qualification_module
from agent_env_foundry._qualification_runner import _is_host_journal, _load_host_journal
from agent_env_foundry.builder import compute_candidate_digest
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.qualification import (
    QualificationConfig,
    QualificationFailure,
    freeze_expected_relations,
    prepare_qualification_workspace,
    run_qualification,
    validate_evidence_rows,
    validate_negative_discrimination,
    validate_predicate_carrier,
    validate_probe_bundle,
)
from agent_env_foundry.release import canonical_bytes, compute_payload_digest, verify_release
from agent_env_foundry.research import BuilderProjection
from agent_env_foundry.semantics_authoring import freeze_expected_task_semantics


def _projection(count: int = 24) -> BuilderProjection:
    requirements = tuple(
        {
            "id": f"REQ-{index:03d}",
            "kind": "refusals" if index == 4 else "workflows",
            "state_relation": f"relation {index}",
            "observable_relation": f"observable {index}",
            "falsifiable_consequence": f"counterexample {index}",
            "need_origins": ["NEED-001"],
            "authority": "need",
            "evidence_refs": [],
        }
        for index in range(1, count)
    )
    initial = (
        {
            "id": f"REQ-{count:03d}",
            "state_relation": "meaningful initial relation",
            "observable_relation": "visible after reset",
            "falsifiable_consequence": "reset is empty",
            "need_origins": ["NEED-001"],
            "authority": "need",
            "evidence_refs": [],
        },
    )
    return BuilderProjection(
        frozen_need={"original_need": "mechanical qualification input"},
        selected_world={"scope": "bounded synthetic world"},
        requirements=requirements,
        initial_world_relations=initial,
        cited_evidence=(),
    )


def _candidate(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "candidate"
    files = {
        "src/pkg/runtime.py": b"VALUE = 1\n",
        "src/pkg/assets/seed.json": b"{}\n",
        "docs/schemas/start.json": b"{}\n",
        "README.md": b"public docs\n",
        "pyproject.toml": b"[project]\nname='mechanical'\nversion='0'\n",
        "uv.lock": b"version = 1\n",
        "release.json": b"{}\n",
        "payload-manifest.json": b'{"files":[]}\n',
        "tests/test_private.py": b"SECRET = True\n",
        "BUILDER_PROJECTION.json": b'{"private":true}\n',
        ".venv/secret.txt": b"private\n",
        "dist/archive.whl": b"private\n",
        ".pytest_cache/private": b"private\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root, compute_candidate_digest(root)


def _predicate_document(expected_document: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "qualification-predicates/1",
        "expected_relations_digest": expected_document["aggregate_digest"],
        "predicates": [
            {
                "requirement_id": relation["requirement_id"],
                "relation_digest": relation["relation_digest"],
                "predicate_id": f"predicate-{index:03d}",
                "acceptance_predicate": (
                    "Accept only when public behavior and independent native evidence "
                    f"establish {relation['requirement_id']}."
                ),
                "near_miss_intent": (
                    f"Reject a reachable near miss that violates {relation['requirement_id']}."
                ),
            }
            for index, relation in enumerate(
                expected_document["relations"],
                start=1,
            )
        ],
    }


def _freeze_predicates_and_stage(prepared: Any) -> None:
    projection = _projection()
    qualification_module.stage_qualification_oracle_inputs(
        prepared,
        projection,
        _expected_task_semantics(projection),
    )
    predicate_path = prepared.root / "QUALIFICATION_PREDICATES.json"
    predicate_path.write_text(json.dumps(_predicate_document(prepared.expected.to_document())))
    validate_predicate_carrier(prepared)
    prepared.stage_candidate_view()


def test_freeze_is_verbatim_candidate_blind_and_digest_stable() -> None:
    projection = _projection()
    first = freeze_expected_relations(projection)
    reordered = BuilderProjection(
        frozen_need=projection.frozen_need,
        selected_world=projection.selected_world,
        requirements=tuple(dict(reversed(tuple(item.items()))) for item in projection.requirements),
        initial_world_relations=projection.initial_world_relations,
        cited_evidence=(),
    )
    second = freeze_expected_relations(reordered)

    original = projection.to_document()
    assert [item.relation for item in first.relations] == [
        *original["requirements"],
        *original["initial_world_relations"],
    ]
    assert [item.requirement_id for item in first.relations] == [
        f"REQ-{index:03d}" for index in range(1, 25)
    ]
    assert first.aggregate_digest == second.aggregate_digest
    assert all(len(item.relation_digest) == 64 for item in first.relations)


def test_prepare_orders_expected_before_candidate_view_and_binds_bytes(tmp_path: Path) -> None:
    candidate, digest = _candidate(tmp_path)
    prepared = prepare_qualification_workspace(
        _projection(), candidate, digest, tmp_path / "qualification"
    )

    expected_path = prepared.root / "EXPECTED_RELATIONS.json"
    assert stat.S_IMODE(expected_path.stat().st_mode) == 0o444
    assert (
        prepared.expected.aggregate_digest
        == json.loads(expected_path.read_text())["aggregate_digest"]
    )
    assert prepared.view_manifest is None
    assert not (prepared.root / "candidate-view").exists()
    _freeze_predicates_and_stage(prepared)
    assert prepared.view_manifest is not None
    copied = {record.path for record in prepared.view_manifest.files}
    assert {
        "src/pkg/runtime.py",
        "src/pkg/assets/seed.json",
        "docs/schemas/start.json",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "release.json",
        "payload-manifest.json",
    } <= copied
    assert not any(
        part in {"tests", ".venv", "dist", ".pytest_cache"}
        for relative in copied
        for part in Path(relative).parts
    )
    assert "BUILDER_PROJECTION.json" not in copied
    prepared.verify_inputs()

    view_dir = prepared.root / "candidate-view/src/pkg"
    view_dir.chmod(0o755)
    with pytest.raises(QualificationFailure, match="directories"):
        prepared.verify_inputs()
    view_dir.chmod(0o555)

    staged = prepared.root / "candidate-view/src/pkg/runtime.py"
    staged.chmod(0o644)
    staged.write_text("VALUE = 2\n")
    with pytest.raises(QualificationFailure, match="candidate view"):
        prepared.verify_inputs()


def test_candidate_digest_checked_before_and_after_staging(tmp_path: Path) -> None:
    candidate, digest = _candidate(tmp_path)
    with pytest.raises(QualificationFailure) as wrong:
        prepare_qualification_workspace(
            _projection(), candidate, "0" * 64, tmp_path / "wrong-digest"
        )
    assert wrong.value.code == "candidate_digest_mismatch"

    prepared = prepare_qualification_workspace(
        _projection(), candidate, digest, tmp_path / "qualification"
    )
    (candidate / "src/pkg/runtime.py").write_text("VALUE = 99\n")
    with pytest.raises(QualificationFailure) as changed:
        prepared.verify_candidate_unchanged()
    assert changed.value.code == "candidate_digest_changed"


def _write_probe_bundle(
    root: Path,
    *,
    public_source: str | None = None,
    native_source: str | None = None,
    expected: Any = None,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    frozen = expected or freeze_expected_relations(_projection())
    predicates = {
        item["requirement_id"]: item
        for item in _predicate_document(frozen.to_document())["predicates"]
    }
    sources = {
        "public_probe.py": public_source or "def run(session, mode):\n    return None\n",
        "native_probe.py": native_source
        or "import sqlite3\nconnection = sqlite3.connect('file:state.db?mode=ro', uri=True)\n",
        "negative_setup.py": "import sqlite3\nconnection = sqlite3.connect('state.db')\n",
    }
    for name, source in sources.items():
        path = root / name
        path.write_text(source)
    return frozen, predicates


def _negative_declarations(
    expected: Any,
    predicates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": relation.requirement_id,
            "negative_run_id": f"negative-{index:03d}",
            "relation": relation.relation,
            "acceptance_predicate": predicates[relation.requirement_id]["acceptance_predicate"],
            "near_miss_intent": predicates[relation.requirement_id]["near_miss_intent"],
        }
        for index, relation in enumerate(expected.relations, start=1)
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        "import generated_environment\n",
        "from tests.test_private import SECRET\n",
        "from agent_env_foundry.environment import load_environment\nimport sqlite3\n",
    ],
)
def test_source_gate_rejects_forbidden_references_before_execution(
    tmp_path: Path, forbidden: str
) -> None:
    expected, predicates = _write_probe_bundle(tmp_path, public_source=forbidden)
    with pytest.raises(QualificationFailure) as caught:
        validate_probe_bundle(tmp_path, expected, predicates)
    assert caught.value.phase == "probe_gate"


@pytest.mark.parametrize(
    "allowed",
    [
        "import importlib\nimportlib.import_module('stdlib_module')\n",
        "import subprocess\nsubprocess.run(['true'])\n",
        "import os\nos.system('true')\n",
    ],
)
def test_source_gate_does_not_police_generic_python_execution(tmp_path: Path, allowed: str) -> None:
    expected, predicates = _write_probe_bundle(tmp_path, public_source=allowed)
    validate_probe_bundle(tmp_path, expected, predicates)


def test_negative_setup_may_edit_the_controlled_candidate_path(tmp_path: Path) -> None:
    expected, predicates = _write_probe_bundle(tmp_path)
    (tmp_path / "negative_setup.py").write_text(
        "from pathlib import Path\n"
        "def mutate(release_root):\n"
        "    path = Path(release_root) / 'src/generated_environment/release.py'\n"
        "    path.write_text(path.read_text().replace('old', 'new', 1))\n"
    )
    validate_probe_bundle(tmp_path, expected, predicates)


def test_host_compiles_probe_manifest_and_binds_all_three_sources(tmp_path: Path) -> None:
    expected, predicates = _write_probe_bundle(tmp_path)
    bundle = validate_probe_bundle(tmp_path, expected, predicates)
    assert len(bundle.negative_declarations) == 24
    manifest = json.loads((tmp_path / "probe_manifest.json").read_text())
    assert manifest["format"] == "qualification-probes/2"
    assert [record["path"] for record in manifest["files"]] == [
        "native_probe.py",
        "negative_setup.py",
        "public_probe.py",
    ]
    assert "required_physical_checks" not in manifest

    (tmp_path / "native_probe.py").chmod(0o644)
    (tmp_path / "native_probe.py").write_text("import json\n")
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._verify_probe_bundle_unchanged(bundle)
    assert caught.value.code == "probe_source_changed"


def test_model_cannot_author_the_host_probe_manifest(tmp_path: Path) -> None:
    expected, predicates = _write_probe_bundle(tmp_path)
    (tmp_path / "probe_manifest.json").write_text('{"model_authored":true}')

    with pytest.raises(QualificationFailure) as caught:
        validate_probe_bundle(tmp_path, expected, predicates)
    assert caught.value.code == "unexpected_probe_output"


def test_native_probe_accepts_dynamic_readonly_sqlite_uri(tmp_path: Path) -> None:
    expected, predicates = _write_probe_bundle(
        tmp_path,
        native_source=(
            "import sqlite3\n"
            "from pathlib import Path\n"
            "path = Path('state.db')\n"
            "connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)\n"
        ),
    )

    validate_probe_bundle(tmp_path, expected, predicates)


def test_native_probe_instructions_do_not_force_sqlite_for_git_state(tmp_path: Path) -> None:
    expected, predicates = _write_probe_bundle(
        tmp_path,
        native_source=(
            "from pathlib import Path\n"
            "root = Path('instance/repository')\n"
            "head = (root / '.git' / 'HEAD').read_text()\n"
            "objects = list((root / '.git' / 'objects').rglob('*'))\n"
        ),
    )

    validate_probe_bundle(tmp_path, expected, predicates)
    instructions = qualification_module._BASE_INSTRUCTIONS + qualification_module._PROBE_PROMPT
    assert "SQLite" not in instructions
    assert "standard reader appropriate" in instructions
    assert "error=null" in instructions
    assert "observation.get('error') or {}" in instructions


def _rows(count: int = 24) -> tuple[Any, list[dict[str, Any]]]:
    expected = freeze_expected_relations(_projection(count))
    rows = []
    for index, relation in enumerate(expected.relations):
        rows.append(
            {
                "requirement_id": relation.requirement_id,
                "public_call_seqs": [index + 1],
                "native_observations": [{"reader": "sqlite3", "fact": {"value": index}}],
                "assertions": [
                    {
                        "assertion_id": f"assert-{index:03d}",
                        "passed": True,
                        "expected": index,
                        "actual": index,
                    }
                ],
                "source_use": {
                    "candidate_source_read": False,
                    "purpose": "none",
                    "paths": [],
                },
            }
        )
    return expected, rows


def _host_journal(
    tmp_path: Path,
    run_id: str,
    calls: list[dict[str, Any]],
    *,
    instance: str = "primary",
) -> Any:
    path = tmp_path / f"{run_id}.journal.jsonl"
    records = [
        {
            "run_id": run_id,
            "seq": sequence,
            "instance": instance,
            "operation": "invoke",
            "arguments": {
                "tool_name": call["tool_name"],
                "arguments": call["arguments"],
            },
            "result": call["observation"],
        }
        for sequence, call in enumerate(calls, start=1)
    ]
    path.write_text("".join(f"{json.dumps(record)}\n" for record in records))
    return _load_host_journal(path, run_id)


def test_host_journal_has_private_provenance_and_canonical_record_shape(
    tmp_path: Path,
) -> None:
    call = {
        "tool_name": "mechanical",
        "arguments": {"value": 7},
        "observation": {"ok": True, "data": {"value": 7}, "error": None},
    }
    journal = _host_journal(tmp_path, "positive-shape", [call])

    assert _is_host_journal(journal)
    assert journal.events[0].to_document() == {
        "run_id": "positive-shape",
        "seq": 1,
        "instance": "primary",
        "operation": "invoke",
        "arguments": {"tool_name": "mechanical", "arguments": {"value": 7}},
        "result": {"ok": True, "data": {"value": 7}, "error": None},
    }


def _journal_for_rows(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    refusal_code: str = "domain.refused",
) -> Any:
    calls: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        observation: dict[str, Any] = {
            "ok": True,
            "data": {"requirement_id": row["requirement_id"]},
            "error": None,
        }
        if index == 3:
            observation = {
                "ok": False,
                "data": None,
                "error": {
                    "code": refusal_code,
                    "message": "refused",
                },
            }
        calls.append(
            {
                "tool_name": "mechanical",
                "arguments": {"requirement_id": row["requirement_id"]},
                "observation": observation,
            }
        )
    return _host_journal(tmp_path, "positive", calls)


def _negative_rows(
    declarations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": declaration["requirement_id"],
            "public_call_seqs": [1],
            "native_observations": [{"reader": "stdlib", "fact": {"changed": False}}],
            "assertions": [
                {
                    "assertion_id": f"assert-{index:03d}",
                    "passed": False,
                    "expected": index,
                    "actual": "near-miss",
                }
            ],
            "source_use": {"purpose": "independent native read", "paths": []},
        }
        for index, declaration in enumerate(declarations)
    ]


def _mechanical_carriers(
    tmp_path: Path,
    declarations: list[dict[str, Any]],
    negative_rows: list[dict[str, Any]],
    *,
    changed: bool = True,
    addition_only: bool = False,
    public_changed: bool = True,
) -> tuple[Any, ...]:
    carriers = []
    for run_id in sorted({item["negative_run_id"] for item in declarations}):
        run_root = tmp_path / run_id
        release_root = run_root / "release"
        instance_root = run_root / "instances"
        release_root.mkdir(parents=True)
        instance_root.mkdir()
        marker = release_root / "marker.bin"
        if not addition_only:
            marker.write_bytes(b"before")
        release_before = runner_module._tree_manifest(release_root)
        instance_before = runner_module._tree_manifest(instance_root)
        if addition_only or changed:
            marker.write_bytes(b"after")
        release_after = runner_module._tree_manifest(release_root)
        instance_after = runner_module._tree_manifest(instance_root)
        declaration = next(item for item in declarations if item["negative_run_id"] == run_id)
        calls = [
            {
                "tool_name": "mechanical",
                "arguments": {"requirement_id": declaration["requirement_id"]},
                "observation": {
                    "ok": True,
                    "data": (
                        {"reported": "changed"}
                        if public_changed
                        else {"requirement_id": declaration["requirement_id"]}
                    ),
                    "error": None,
                },
            }
        ]
        journal = _host_journal(tmp_path, run_id, calls, instance="primary")
        carriers.append(
            runner_module._make_run_carrier(
                run_id,
                release_root,
                instance_root,
                release_before,
                release_after,
                instance_before,
                instance_after,
                journal,
                "a" * 64,
            )
        )
    return tuple(carriers)


def _negative_case(
    tmp_path: Path,
    count: int = 24,
    *,
    changed: bool = True,
    addition_only: bool = False,
    public_changed: bool = True,
) -> tuple[Any, ...]:
    expected, rows = _rows(count)
    validated = validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))
    predicates = {
        item["requirement_id"]: item
        for item in _predicate_document(expected.to_document())["predicates"]
    }
    declarations = _negative_declarations(expected, predicates)
    negatives = _negative_rows(declarations)
    for row, negative in zip(rows, negatives, strict=True):
        negative["assertions"][0]["expected"] = row["assertions"][0]["expected"]
    carriers = _mechanical_carriers(
        tmp_path / "carriers",
        declarations,
        negatives,
        changed=changed,
        addition_only=addition_only,
        public_changed=public_changed,
    )
    bundle = qualification_module.ProbeBundle(tmp_path, tuple(declarations), "f" * 64)
    return expected, validated, predicates, bundle, negatives, carriers


def test_evidence_requires_exact_24_relations(tmp_path: Path) -> None:
    expected, rows = _rows()
    validated = validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))
    assert len(validated) == 24
    assert {item.requirement_id for item in validated} == {
        f"REQ-{index:03d}" for index in range(1, 25)
    }


def test_model_assertion_cannot_self_authorize_physical_coverage(tmp_path: Path) -> None:
    expected, rows = _rows(1)
    rows[0]["assertions"][0]["covers"] = ["reload_persistence"]

    with pytest.raises(QualificationFailure) as caught:
        validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))

    assert caught.value.code == "assertion_failed"


def test_evidence_public_calls_must_come_from_host_journal(tmp_path: Path) -> None:
    expected, rows = _rows()
    rows[0]["public_call_seqs"] = [999]
    with pytest.raises(QualificationFailure) as caught:
        validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))
    assert caught.value.code == "public_call_missing"


@pytest.mark.parametrize("sequences", ([1, 1], [2, 1]))
def test_evidence_public_call_sequences_are_unique_and_ordered(
    sequences: list[int], tmp_path: Path
) -> None:
    expected, rows = _rows(2)
    rows[0]["public_call_seqs"] = sequences

    with pytest.raises(QualificationFailure) as caught:
        validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))

    assert caught.value.code == "public_call_sequence_invalid"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda rows: rows.__setitem__(0, {**rows[0], "requirement_id": "REQ-999"}),
            "unknown_relation",
        ),
        (lambda rows: rows.pop(), "missing_relation_coverage"),
        (lambda rows: rows[0].__setitem__("relation_digest", "0" * 64), "evidence_invalid"),
        (lambda rows: rows[0]["assertions"][0].__setitem__("passed", False), "assertion_failed"),
        (lambda rows: rows[0]["assertions"][0].pop("actual"), "assertion_failed"),
        (lambda rows: rows[0].__setitem__("native_observations", []), "native_observation_missing"),
    ],
)
def test_evidence_rejects_each_host_contract_violation(
    mutation: Any, expected_code: str, tmp_path: Path
) -> None:
    expected, rows = _rows()
    mutation(rows)
    with pytest.raises(QualificationFailure) as caught:
        validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))
    issue_codes = {issue["code"] for issue in caught.value.details.get("issues", [])}
    assert caught.value.code == expected_code or (
        caught.value.code == "evidence_semantic_failures" and expected_code in issue_codes
    )


@pytest.mark.parametrize("code", ("contract.invalid_arguments", "internal_error"))
def test_refusal_requirement_must_bind_a_real_business_refusal(code: str, tmp_path: Path) -> None:
    expected, rows = _rows()
    with pytest.raises(QualificationFailure) as caught:
        validate_evidence_rows(
            rows,
            expected,
            _journal_for_rows(tmp_path, rows, refusal_code=code),
        )
    assert caught.value.code == "business_refusal_missing"


def test_24_relation_negative_validator_fixture_is_mechanical_only(
    tmp_path: Path,
) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path)
    result = validate_negative_discrimination(
        bundle, negatives, rows, expected, predicates, carriers, "a" * 64
    )
    assert len(result) == 24


def test_negative_discrimination_may_be_scoped_to_taskable_requirements(
    tmp_path: Path,
) -> None:
    expected, rows = _rows(4)
    validated = validate_evidence_rows(rows, expected, _journal_for_rows(tmp_path, rows))
    predicates = {
        item["requirement_id"]: item
        for item in _predicate_document(expected.to_document())["predicates"]
    }
    required = {"REQ-001", "REQ-003"}
    declarations = [
        item
        for item in _negative_declarations(expected, predicates)
        if item["requirement_id"] in required
    ]
    negatives = _negative_rows(declarations)
    by_id = {row["requirement_id"]: row for row in rows}
    for negative in negatives:
        baseline = by_id[negative["requirement_id"]]
        negative["assertions"][0]["assertion_id"] = baseline["assertions"][0]["assertion_id"]
        negative["assertions"][0]["expected"] = baseline["assertions"][0]["expected"]
    carriers = _mechanical_carriers(
        tmp_path / "taskable-carriers",
        declarations,
        negatives,
    )
    bundle = qualification_module.ProbeBundle(tmp_path, tuple(declarations), "f" * 64)

    result = validate_negative_discrimination(
        bundle,
        negatives,
        validated,
        expected,
        predicates,
        carriers,
        "a" * 64,
        required_negative_ids=required,
    )

    assert {item["requirement_id"] for item in result} == required


def test_negative_baseline_and_assertion_identity_must_match(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path, 1)
    negatives[0]["assertions"][0]["assertion_id"] = "different-assertion"

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_assertion_mismatch"


def test_negative_must_keep_the_baseline_expected_fact(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path, 1)
    negatives[0]["assertions"][0]["expected"] = "different"

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_assertion_mismatch"


def test_negative_call_must_be_bound_to_its_exact_run_journal(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path, 2)
    negatives[0]["public_call_seqs"] = [999]

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_call_not_in_journal"


def test_negative_discrimination_must_cover_all_24_relations(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path)
    incomplete = qualification_module.ProbeBundle(
        bundle.root, bundle.negative_declarations[:-1], bundle.bundle_digest
    )

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            incomplete, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "missing_negative_relation_coverage"


def test_negative_feedback_reports_all_relation_failures_at_once(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(tmp_path)
    for negative in negatives:
        negative["assertions"][0]["assertion_id"] = "wrong-" + negative["requirement_id"]

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    issues = caught.value.details["issues"]
    assert caught.value.code == "negative_assertion_mismatch"
    assert [issue["requirement_id"] for issue in issues] == [
        f"REQ-{index:03d}" for index in range(1, 25)
    ]
    feedback = qualification_module._render_probe_feedback(caught.value)
    assert all(label in feedback for label in ("REJECTED", "ALL_FINDINGS", "REPAIR", "RESUBMIT"))


def test_negative_setup_requires_controlled_root_byte_change(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(
        tmp_path, 1, changed=False
    )

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_physical_noop"


def test_added_marker_is_not_a_semantic_near_miss(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(
        tmp_path, 1, addition_only=True
    )

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_physical_noop"


def test_near_miss_must_change_matching_public_behavior(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, carriers = _negative_case(
        tmp_path, 1, public_changed=False
    )

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, carriers, "a" * 64
        )
    assert caught.value.code == "negative_public_behavior_unchanged"


def test_public_behavior_comparison_preserves_repeated_call_occurrences() -> None:
    first = {
        "scope": {"instance": "case", "open_epoch": 1, "reset_epoch": 1},
        "tool_name": "inspect",
        "arguments": {"record_id": "record-1"},
        "observation": {"ok": True, "data": {"state": "before"}, "error": None},
    }
    second = {
        **first,
        "observation": {"ok": True, "data": {"state": "after"}, "error": None},
    }

    assert not qualification_module._public_behavior_changed(
        [first, second],
        [first, second],
    )
    assert qualification_module._public_behavior_changed(
        [first, second],
        [first, {**second, "observation": {"ok": True, "data": {"state": "wrong"}, "error": None}}],
    )


def test_public_behavior_comparison_does_not_pair_different_lifecycle_scopes() -> None:
    baseline = {
        "scope": {"instance": "case", "open_epoch": 1, "reset_epoch": 1},
        "tool_name": "inspect",
        "arguments": {},
        "observation": {"ok": True, "data": {"state": "before"}, "error": None},
    }
    different_scope = {
        **baseline,
        "scope": {"instance": "case", "open_epoch": 2, "reset_epoch": 1},
        "observation": {"ok": True, "data": {"state": "after"}, "error": None},
    }

    assert not qualification_module._public_behavior_changed([baseline], [different_scope])


def test_failed_close_reopen_is_owned_by_candidate(tmp_path: Path) -> None:
    journal = _journal_from_events(
        tmp_path,
        "reload-failure",
        [
            ("persist", "reset", {"start": None}, {"state": "initial"}),
            ("persist", "close", {}, None),
            ("persist", "open", {}, {"attached": True}),
            (
                "persist",
                "invoke",
                {"tool_name": "inspect", "arguments": {}},
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "internal_error",
                        "message": "reset must be called before using the environment",
                    },
                },
            ),
        ],
    )

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._reject_failed_reload_attempt(journal)

    assert caught.value.phase == "candidate_execution"
    assert caught.value.code == "candidate_reload_failed"
    assert caught.value.details["instance"] == "persist"
    assert caught.value.details["seq"] == 4
    finding = caught.value.candidate_finding
    assert finding is not None
    assert finding.contract_clause == "factory_reattachment"
    assert finding.arguments == {"tool_name": "inspect", "arguments": {}}


def test_failed_close_reopen_host_exception_has_safe_candidate_finding(
    tmp_path: Path,
) -> None:
    journal = _journal_from_events(
        tmp_path,
        "reload-host-exception",
        [
            ("persist", "reset", {"start": None}, {"state": "initial"}),
            ("persist", "close", {}, None),
            ("persist", "open", {}, {"attached": True}),
            (
                "persist",
                "invoke",
                {"tool_name": "inspect", "arguments": {}},
                {
                    "host_exception": {
                        "type": "EnvironmentRuntimeError",
                        "message": "PRIVATE_PROBE_PATH/public_probe.py",
                    }
                },
            ),
        ],
    )

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._reject_failed_reload_attempt(journal)

    finding = caught.value.candidate_finding
    assert caught.value.code == "candidate_reload_failed"
    assert finding is not None
    assert finding.observation is None
    assert finding.runtime_error == "EnvironmentRuntimeError"
    assert "PRIVATE_PROBE_PATH" not in json.dumps(finding.to_document())


def test_closed_handle_without_fresh_open_is_not_misattributed_to_candidate(
    tmp_path: Path,
) -> None:
    journal = _journal_from_events(
        tmp_path,
        "stale-handle",
        [
            ("persist", "close", {}, None),
            (
                "persist",
                "invoke",
                {"tool_name": "inspect", "arguments": {}},
                {
                    "ok": False,
                    "data": None,
                    "error": {"code": "internal_error", "message": "closed handle"},
                },
            ),
        ],
    )

    qualification_module._reject_failed_reload_attempt(journal)


def _journal_from_events(
    tmp_path: Path,
    run_id: str,
    events: list[tuple[str, str, dict[str, Any], Any]],
) -> Any:
    path = tmp_path / f"{run_id}.events.jsonl"
    records = [
        {
            "run_id": run_id,
            "seq": seq,
            "instance": instance,
            "operation": operation,
            "arguments": arguments,
            "result": result,
        }
        for seq, (instance, operation, arguments, result) in enumerate(events, start=1)
    ]
    path.write_text("".join(f"{json.dumps(record)}\n" for record in records))
    return _load_host_journal(path, run_id)


def _success_observation(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _invoke_event(
    instance: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> tuple[str, str, dict[str, Any], Any]:
    return (instance, "invoke", {"tool_name": tool_name, "arguments": arguments}, result)


def test_host_probe_topology_records_attempts_without_claiming_semantic_truth(
    tmp_path: Path,
) -> None:
    journal = _journal_from_events(
        tmp_path,
        "topology",
        [
            ("a", "open", {}, {"attached": True}),
            ("a", "reset", {"start": {"mode": "variant"}}, {"incidental_id": "one"}),
            _invoke_event("a", "produce", {}, _success_observation({"token": "A1"})),
            _invoke_event("a", "consume", {"token": "A1"}, _success_observation({"used": True})),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            _invoke_event(
                "a",
                "act",
                {},
                {"ok": False, "data": None, "error": {"code": "domain.refused"}},
            ),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            ("a", "reset", {"start": {"mode": "variant"}}, {"incidental_id": "two"}),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            ("a", "close", {}, None),
            ("a", "open", {}, {"attached": True}),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            ("a", "close", {}, None),
            ("b", "open", {}, {"attached": True}),
            ("b", "reset", {"start": {"mode": "variant"}}, {"incidental_id": "three"}),
            _invoke_event("b", "inspect", {}, _success_observation({"state": "same"})),
            ("b", "close", {}, None),
        ],
    )

    witnesses = qualification_module._probe_topology_witnesses(journal)

    assert set(witnesses) == {
        "business_refusal_bracket",
        "fresh_reopen_invoke",
        "nondefault_start_distinct_instances",
        "reset_after_activity",
        "same_instance_value_reuse",
        "same_start_distinct_instances",
    }
    qualification_module._require_probe_topology(
        journal,
        {
            "type": "object",
            "properties": {"mode": {"type": "string"}},
            "additionalProperties": False,
        },
    )


@pytest.mark.parametrize("refusal_code", ("contract.invalid_arguments", "internal_error"))
def test_probe_topology_rejects_cross_instance_and_nonbusiness_refusal_shortcuts(
    refusal_code: str,
    tmp_path: Path,
) -> None:
    journal = _journal_from_events(
        tmp_path,
        "topology-shortcuts",
        [
            ("a", "open", {}, {"attached": True}),
            ("a", "reset", {"start": {"mode": "variant"}}, {"state": "initial"}),
            _invoke_event("a", "produce", {}, _success_observation({"token": "TOKEN-123"})),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            _invoke_event(
                "a",
                "act",
                {},
                {"ok": False, "data": None, "error": {"code": refusal_code}},
            ),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            ("a", "reset", {"start": {"mode": "variant"}}, {"state": "initial"}),
            ("b", "open", {}, {"attached": True}),
            _invoke_event(
                "b", "consume", {"token": "TOKEN-123"}, _success_observation({"used": True})
            ),
        ],
    )

    witnesses = qualification_module._probe_topology_witnesses(journal)

    assert "same_instance_value_reuse" not in witnesses
    assert "business_refusal_bracket" not in witnesses
    assert "nondefault_start_distinct_instances" not in witnesses


def test_probe_topology_rejects_pre_reset_shortcuts(tmp_path: Path) -> None:
    journal = _journal_from_events(
        tmp_path,
        "pre-reset-shortcuts",
        [
            ("a", "open", {}, {"attached": True}),
            _invoke_event("a", "produce", {}, _success_observation({"token": "A1"})),
            _invoke_event("a", "consume", {"token": "A1"}, _success_observation({"used": True})),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            _invoke_event(
                "a",
                "act",
                {},
                {"ok": False, "data": None, "error": {"code": "domain.refused"}},
            ),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
            ("a", "close", {}, None),
            ("a", "open", {}, {"attached": True}),
            _invoke_event("a", "inspect", {}, _success_observation({"state": "same"})),
        ],
    )

    witnesses = qualification_module._probe_topology_witnesses(journal)

    assert "same_instance_value_reuse" not in witnesses
    assert "business_refusal_bracket" not in witnesses
    assert "fresh_reopen_invoke" not in witnesses


def test_pre_reset_reopen_failure_is_not_misattributed_to_candidate(tmp_path: Path) -> None:
    journal = _journal_from_events(
        tmp_path,
        "pre-reset-reopen",
        [
            ("case", "open", {}, {"attached": True}),
            ("case", "close", {}, None),
            ("case", "open", {}, {"attached": True}),
            _invoke_event(
                "case",
                "inspect",
                {},
                {
                    "ok": False,
                    "data": None,
                    "error": {"code": "internal_error", "message": "reset required"},
                },
            ),
        ],
    )

    qualification_module._reject_failed_reload_attempt(journal)


def test_nondefault_start_topology_is_required_only_when_schema_publishes_fields(
    tmp_path: Path,
) -> None:
    journal = _journal_from_events(tmp_path, "empty-topology", [])
    empty_start = {"type": "object", "properties": {}, "additionalProperties": False}
    field_start = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "additionalProperties": False,
    }
    referenced_start = {
        "type": "object",
        "allOf": [{"$ref": "#/$defs/start"}],
        "$defs": {"start": field_start},
        "additionalProperties": False,
    }

    assert (
        "nondefault_start_distinct_instances"
        not in qualification_module._required_probe_topology(empty_start)
    )
    assert "nondefault_start_distinct_instances" in qualification_module._required_probe_topology(
        field_start
    )
    assert "nondefault_start_distinct_instances" in qualification_module._required_probe_topology(
        referenced_start
    )
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._require_probe_topology(journal, field_start)
    assert caught.value.code == "public_probe_topology_incomplete"
    assert "nondefault_start_distinct_instances" in caught.value.details["missing"]


def test_execute_probes_rejects_missing_topology_before_native_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = _projection(1)
    candidate, digest = _release_shaped_candidate(tmp_path)
    candidate_python = candidate / ".venv/bin/python"
    candidate_python.parent.mkdir(parents=True)
    candidate_python.write_text("mechanical")
    prepared = prepare_qualification_workspace(
        projection,
        candidate,
        digest,
        tmp_path / "qualification-topology",
    )
    journal = _journal_from_events(
        tmp_path,
        "missing-topology",
        [
            ("case", "open", {}, {"attached": True}),
            ("case", "reset", {"start": None}, {"state": "initial"}),
        ],
    )
    monkeypatch.setattr(qualification_module, "_verify_probe_bundle_unchanged", lambda _: None)
    monkeypatch.setattr(qualification_module, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        qualification_module,
        "_execute_public_probe",
        lambda *args, **kwargs: journal,
    )

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._execute_probes(
            prepared,
            qualification_module.ProbeBundle(tmp_path, (), "f" * 64),
            QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
        )

    assert caught.value.code == "public_probe_topology_incomplete"


def test_candidate_execution_failure_remains_candidate_owned_at_api_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = _projection()
    candidate, digest = _release_shaped_candidate(tmp_path)

    def fail_candidate(*args: Any, **kwargs: Any) -> Any:
        raise QualificationFailure(
            "candidate_execution",
            "candidate_reload_failed",
            "freshly reopened environment cannot invoke without reset",
        )

    monkeypatch.setattr(qualification_module, "_author_probes", fail_candidate)
    result = run_qualification(
        projection,
        candidate,
        digest,
        tmp_path / "qualification-attribution",
        expected_task_semantics=_expected_task_semantics(projection),
        config=QualificationConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert result.status == "candidate_defect"
    assert result.failure_code == "candidate_reload_failed"


def test_negative_requires_per_run_source_copy_carrier(tmp_path: Path) -> None:
    expected, rows, predicates, bundle, negatives, _ = _negative_case(tmp_path, 1)

    with pytest.raises(QualificationFailure) as caught:
        validate_negative_discrimination(
            bundle, negatives, rows, expected, predicates, (), "a" * 64
        )
    assert caught.value.code == "negative_run_carrier_missing"


def test_model_rows_without_host_execution_carriers_are_rejected() -> None:
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._require_host_outputs({"rows": [], "negative_rows": []})
    assert caught.value.code == "host_carrier_missing"


def test_predicate_authoring_turn_is_blind_then_frozen_before_source_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate, digest = _candidate(tmp_path)
    workspace = tmp_path / "qualification"
    predicate_path = workspace / "QUALIFICATION_PREDICATES.json"
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "mechanical-key")
    observed: dict[str, Any] = {"predicate_calls": 0, "thread_starts": 0, "probe_runs": 0}
    authored_bytes: bytes | None = None

    def predicate_turn(**kwargs: Any) -> dict[str, Any]:
        nonlocal authored_bytes
        observed["predicate_calls"] += 1
        expected_path = workspace / "EXPECTED_RELATIONS.json"
        document = json.loads(expected_path.read_text())
        provider_input = json.loads(kwargs["input_text"])
        provider_schema = kwargs["schema"]
        observed.update(
            predicate_candidate_view_absent=not (workspace / "candidate-view").exists(),
            expected_mode=stat.S_IMODE(expected_path.stat().st_mode),
            predicate_count=len(document["relations"]),
            provider_input_has_digest="digest" in json.dumps(provider_input),
            provider_schema_requests_binding=any(
                name in json.dumps(provider_schema)
                for name in ("requirement_id", "relation_digest", "predicate_id")
            ),
        )
        carrier = _predicate_document(document)
        authored_bytes = canonical_bytes(carrier)
        return {
            "predicates": [
                {
                    "acceptance_predicate": predicate["acceptance_predicate"],
                    "near_miss_intent": predicate["near_miss_intent"],
                }
                for predicate in carrier["predicates"]
            ]
        }

    class Result:
        final_response = ""

    class ProbeThread:
        id = "mechanical-probe-thread"

        def run(self, prompt: str) -> Result:
            observed["probe_runs"] += 1
            observed.update(
                probe_candidate_view_present=(workspace / "candidate-view").is_dir(),
                predicate_bytes_frozen=predicate_path.read_bytes() == authored_bytes,
                predicate_mode=stat.S_IMODE(predicate_path.stat().st_mode),
            )
            _write_probe_bundle(workspace, public_source="import generated_environment\n")
            return Result()

    class ProbeCodex:
        def __init__(self, config: Any) -> None:
            self.config = config
            observed["permission_overrides"] = config.config_overrides[-4:]

        def __enter__(self) -> ProbeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_start(self, **kwargs: Any) -> ProbeThread:
            observed["thread_starts"] += 1
            observed["sandbox_absent"] = "sandbox" not in kwargs
            return ProbeThread()

    monkeypatch.setattr(qualification_module, "_run_fresh_json_turn", predicate_turn)
    monkeypatch.setattr(qualification_module, "Codex", ProbeCodex)
    result = run_qualification(
        _projection(),
        candidate,
        digest,
        workspace,
        expected_task_semantics=_expected_task_semantics(_projection()),
        config=QualificationConfig(max_turns=1),
    )
    assert result.status != "passed"
    assert result.status == "probe_defect"
    assert observed == {
        "predicate_calls": 1,
        "thread_starts": 1,
        "probe_runs": 1,
        "predicate_candidate_view_absent": True,
        "expected_mode": 0o444,
        "predicate_count": 24,
        "provider_input_has_digest": False,
        "provider_schema_requests_binding": False,
        "probe_candidate_view_present": True,
        "predicate_bytes_frozen": True,
        "predicate_mode": 0o444,
        "permission_overrides": qualification_module._codex_workspace_permission_overrides(
            "foundry_qualification",
            workspace,
        ),
        "sandbox_absent": True,
    }


def test_candidate_repair_reuses_exact_candidate_blind_predicate_carrier(
    tmp_path: Path,
) -> None:
    projection = _projection(3)
    candidate, digest = _release_shaped_candidate(tmp_path)
    expected_semantics = _expected_task_semantics(projection)
    source = prepare_qualification_workspace(
        projection,
        candidate,
        digest,
        tmp_path / "qualification-source",
    )
    qualification_module.stage_qualification_oracle_inputs(
        source,
        projection,
        expected_semantics,
    )
    source_path = source.root / qualification_module.PREDICATE_NAME
    source_path.write_bytes(canonical_bytes(_predicate_document(source.expected.to_document())))
    source_digest = qualification_module.validate_predicate_carrier(source)

    target = prepare_qualification_workspace(
        projection,
        candidate,
        digest,
        tmp_path / "qualification-target",
    )
    qualification_module.stage_qualification_oracle_inputs(
        target,
        projection,
        expected_semantics,
    )
    reused_digest = qualification_module._reuse_predicate_carrier(
        target,
        source.root,
        source_digest,
    )

    assert reused_digest == source_digest
    assert (
        target.root / qualification_module.PREDICATE_NAME
    ).read_bytes() == source_path.read_bytes()
    assert target.predicates == source.predicates
    assert not (target.root / "candidate-view").exists()

    source_path.chmod(0o644)
    source_path.write_bytes(source_path.read_bytes() + b"\n")
    tampered = prepare_qualification_workspace(
        projection,
        candidate,
        digest,
        tmp_path / "qualification-tampered",
    )
    qualification_module.stage_qualification_oracle_inputs(
        tampered,
        projection,
        expected_semantics,
    )
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._reuse_predicate_carrier(
            tampered,
            source.root,
            source_digest,
        )
    assert caught.value.code == "predicate_reuse_digest_mismatch"


def test_each_qualification_attempt_has_a_distinct_codex_home(tmp_path: Path) -> None:
    assert qualification_module._qualifier_codex_home(tmp_path / "qualification") == (
        tmp_path / "qualification-codex-home"
    )
    assert qualification_module._qualifier_codex_home(tmp_path / "qualification-attempt-002") == (
        tmp_path / "qualification-attempt-002-codex-home"
    )


def test_agent_verdict_cannot_bypass_source_gate_or_reach_executor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate, digest = _candidate(tmp_path)
    workspace = tmp_path / "qualification"
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "mechanical-key")
    executed = False

    class Result:
        final_response = "PASSED"

    class Thread:
        id = "mechanical-thread"

        def run(self, prompt: str) -> Result:
            _write_probe_bundle(
                workspace,
                public_source="import generated_environment\n",
            )
            return Result()

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            self.config = config

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def thread_start(self, **kwargs: Any) -> Thread:
            return Thread()

    def forbidden_executor(*args: Any, **kwargs: Any) -> Any:
        nonlocal executed
        executed = True
        raise AssertionError("source gate was bypassed")

    def predicate_turn(**kwargs: Any) -> dict[str, Any]:
        expected = json.loads((workspace / "EXPECTED_RELATIONS.json").read_text())
        carrier = _predicate_document(expected)
        return {
            "predicates": [
                {
                    "acceptance_predicate": predicate["acceptance_predicate"],
                    "near_miss_intent": predicate["near_miss_intent"],
                }
                for predicate in carrier["predicates"]
            ]
        }

    monkeypatch.setattr(qualification_module, "_run_fresh_json_turn", predicate_turn)
    monkeypatch.setattr(qualification_module, "Codex", FakeCodex)
    monkeypatch.setattr(qualification_module, "_execute_probes", forbidden_executor)
    result = run_qualification(
        _projection(),
        candidate,
        digest,
        workspace,
        expected_task_semantics=_expected_task_semantics(_projection()),
        config=QualificationConfig(max_turns=1),
    )
    assert result.status == "probe_defect"
    assert result.failure_code == "probe_source_forbidden"
    assert not executed


def test_codex_probe_turn_timeout_interrupts_and_fails_closed() -> None:
    started = threading.Event()
    released = threading.Event()
    interrupted = threading.Event()

    class Handle:
        def run(self) -> None:
            started.set()
            released.wait(1.0)

        def interrupt(self) -> None:
            interrupted.set()
            released.set()

    class Thread:
        def turn(self, prompt: str) -> Handle:
            return Handle()

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._run_codex_turn(Thread(), "write probes", 0.01)
    assert started.is_set()
    assert interrupted.is_set()
    assert caught.value.phase == "infrastructure"
    assert caught.value.code == "qualifier_turn_timeout"


def _release_shaped_candidate(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "release-candidate"
    source = b"""\
BRANCH = "baseline"

class Environment:
    def __init__(self, instance):
        self.instance = instance

    def reset(self, start=None):
        return {"branch": BRANCH}

    def tools(self):
        return ({
            "name": "branch",
            "description": "Return the state-independent branch",
            "input_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
            },
            "output_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["branch"],
                "properties": {"branch": {"type": "string"}},
                "additionalProperties": False,
            },
        },)

    def invoke(self, tool_name, arguments):
        return {"ok": True, "data": {"branch": BRANCH}, "error": None}

    def close(self):
        return None

def make_environment(instance):
    return Environment(instance)
"""
    payload = {
        "src/mechanical_copy_environment/__init__.py": b"",
        "src/mechanical_copy_environment/release.py": source,
        "schemas/start.json": canonical_bytes(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
            }
        ),
        "schemas/reset.json": canonical_bytes(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["branch"],
                "properties": {"branch": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
    }
    records = []
    for relative, content in payload.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)
        records.append(
            {
                "path": relative,
                "type": "file",
                "mode": 0o644,
                "digest": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {"files": sorted(records, key=lambda item: item["path"])}
    (root / "payload-manifest.json").write_bytes(canonical_bytes(manifest))
    descriptor = {
        "format": "environment-release/1",
        "canonicalization": "rfc8785",
        "hash": "sha256",
        "payload_manifest": "payload-manifest.json",
        "payload_digest": compute_payload_digest(manifest),
        "environment_factory": "mechanical_copy_environment.release:make_environment",
        "start_schema": "schemas/start.json",
        "reset_observation_schema": "schemas/reset.json",
    }
    (root / "release.json").write_bytes(canonical_bytes(descriptor))
    (root / ".venv/secret.txt").parent.mkdir()
    (root / ".venv/secret.txt").write_text("must not copy")
    (root / "unlisted.txt").write_text("must not copy")
    verify_release(root)
    return root, compute_candidate_digest(root)


def _expected_task_semantics(projection: BuilderProjection) -> Any:
    requirement_ids = [
        item["id"]
        for item in (
            *projection.to_document()["requirements"],
            *projection.to_document()["initial_world_relations"],
        )
    ]
    taskable_ids = requirement_ids[:2]
    document = {
        "requirements": [
            {
                "requirement_id": requirement_id,
                "disposition": "Taskable" if requirement_id in taskable_ids else "NotTaskable",
                "rationale": "mechanical author-input fixture",
                "preconditions": ["world exists"] if requirement_id in taskable_ids else [],
                "outcomes": ["relation holds"] if requirement_id in taskable_ids else [],
                "refusals": [],
                "collateral_constraints": [],
                "workflow_ids": ["mechanical-workflow"],
            }
            for requirement_id in requirement_ids
        ],
        "capabilities": [
            {
                "capability_id": f"capability-{index}",
                "requirement_ids": [requirement_id],
                "workflow_ids": ["mechanical-workflow"],
                "actor_role": "operator",
                "task_kind": "state_change" if index == 1 else "query",
                "intent_label": f"exercise relation {index}",
                "answer_fields": (
                    []
                    if index == 1
                    else [
                        {
                            "field_id": f"relation-{index}-answer",
                            "public_label": f"Relation {index} answer",
                        }
                    ]
                ),
            }
            for index, requirement_id in enumerate(taskable_ids, start=1)
        ],
        "composition_rules": [],
        "conditions": [],
    }
    return freeze_expected_task_semantics(projection, document)


def _semantics_input_journal(tmp_path: Path) -> Any:
    tool = {
        "name": "branch",
        "description": "Return the state-independent branch",
        "input_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
        },
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["branch"],
            "properties": {"branch": {"type": "string"}},
            "additionalProperties": False,
        },
    }
    events = [
        ("reset", {"start": None}, {"branch": "baseline"}),
        ("tools", {}, [tool]),
        (
            "invoke",
            {"tool_name": "branch", "arguments": {}},
            {"ok": True, "data": {"branch": "baseline"}, "error": None},
        ),
    ]
    path = tmp_path / "semantics-input.journal.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                {
                    "run_id": "semantics-input",
                    "seq": sequence,
                    "instance": "baseline",
                    "operation": operation,
                    "arguments": arguments,
                    "result": result,
                }
            )
            + "\n"
            for sequence, (operation, arguments, result) in enumerate(events, start=1)
        )
    )
    return _load_host_journal(path, "semantics-input")


def test_semantics_author_inputs_reuse_qualification_view_and_host_journal(
    tmp_path: Path,
) -> None:
    projection = _projection(3)
    candidate, digest = _release_shaped_candidate(tmp_path)
    prepared = prepare_qualification_workspace(
        projection,
        candidate,
        digest,
        tmp_path / "qualification",
    )
    expected_task_semantics = _expected_task_semantics(projection)
    qualification_module.stage_qualification_oracle_inputs(
        prepared,
        projection,
        expected_task_semantics,
    )
    for name in ("EXPECTED_TASK_SEMANTICS.json", "NATIVE_ORACLE_CONTRACT.md"):
        path = prepared.root / name
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o444
        assert name in prepared.input_digests
    with pytest.raises(QualificationFailure, match="Host-created"):
        qualification_module.prepare_semantics_author_workspace(
            prepared,
            projection,
            expected_task_semantics,
            object(),
        )
    workspace = qualification_module.prepare_semantics_author_workspace(
        prepared,
        projection,
        expected_task_semantics,
        _semantics_input_journal(tmp_path),
    )

    assert workspace.root == prepared.root / "semantics-author"
    assert {path.name for path in workspace.root.iterdir()} == {
        "EXPECTED_TASK_SEMANTICS.json",
        "PUBLIC_SURFACE.json",
        "TASK_SEMANTICS_CONTRACT.md",
        "CANDIDATE_VIEW_MANIFEST.json",
        "candidate-view",
    }
    public_surface = json.loads((workspace.root / "PUBLIC_SURFACE.json").read_text())
    assert public_surface["candidate_digest"] == digest
    assert public_surface["candidate_view_digest"] == workspace.view_manifest.view_digest
    assert public_surface["actor_factory"] == (
        "mechanical_copy_environment.release:make_environment"
    )
    assert [item["name"] for item in public_surface["tool_specs"]] == ["branch"]
    assert [item["operation"] for item in public_surface["public_probe_facts"]] == [
        "reset",
        "invoke",
    ]
    view_manifest = json.loads((workspace.root / "CANDIDATE_VIEW_MANIFEST.json").read_text())
    assert "src/mechanical_copy_environment/release.py" in {
        item["path"] for item in view_manifest["files"]
    }
    assert not (workspace.root / "candidate-view/.venv").exists()
    assert all(
        stat.S_IMODE((workspace.root / name).stat().st_mode) == 0o444
        for name in workspace.input_digests
    )
    contract = (workspace.root / "TASK_SEMANTICS_CONTRACT.md").read_text()
    for required in (
        "start_cases",
        "inspect",
        "capabilities",
        "enumerate_bindings",
        "evaluate_atom",
        "evaluate_condition",
        "protected_binding_schema",
        "public_descriptor_schema",
        "supported_goal_kinds",
        "BindingCandidateDocument",
        "AtomCheckResultDocument",
        "ConditionCheckResultDocument",
        'task_kind="query"',
        "schema-valid wrong or stale answer",
        "same public binding document",
        "successful state-changing call",
        "terminal state with an empty trace",
        "distinct reset input",
        "must not import the actor package",
        "must not mutate",
    ):
        assert required in contract
    workspace.verify_inputs()

    surface_path = workspace.root / "PUBLIC_SURFACE.json"
    surface_path.chmod(0o644)
    surface_path.write_text("{}")
    with pytest.raises(QualificationFailure, match="changed"):
        workspace.verify_inputs()


def test_passing_actor_qualification_stages_semantics_inputs_before_return(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = _projection(3)
    candidate, digest = _release_shaped_candidate(tmp_path)
    journal = _semantics_input_journal(tmp_path)

    def admitted_actor_evidence(
        prepared: Any,
        config: Any,
        *,
        predicate_source_root: Path | None = None,
        predicate_source_digest: str | None = None,
    ) -> tuple[Any, ...]:
        del config, predicate_source_root, predicate_source_digest
        rows = tuple(
            qualification_module.EvidenceRow(
                relation.requirement_id,
                relation.relation_digest,
                {"mechanical": True},
            )
            for relation in prepared.expected.relations
        )
        codex_home = tmp_path / "qualification-codex-home"
        codex_home.mkdir(exist_ok=True)
        return (
            qualification_module.ProbeBundle(prepared.root, (), "b" * 64),
            rows,
            tuple({"requirement_id": row.requirement_id} for row in rows[:2]),
            (),
            journal,
            "qualifier-thread",
            codex_home,
        )

    monkeypatch.setattr(qualification_module, "_author_probes", admitted_actor_evidence)
    result = run_qualification(
        projection,
        candidate,
        digest,
        tmp_path / "qualification",
        expected_task_semantics=_expected_task_semantics(projection),
        config=QualificationConfig(max_turns=1),
    )

    assert result.status == "passed"
    assert result.qualifier_thread_id == "qualifier-thread"
    assert result.qualifier_codex_home == tmp_path / "qualification-codex-home"
    assert result.semantics_author_inputs is not None
    assert result.semantics_author_inputs.root == (tmp_path / "qualification/semantics-author")
    assert result.expected_task_semantics_digest is not None
    assert result.public_surface_digest is not None


def test_tree_manifest_records_symlink_and_mode_without_following(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("target")
    target.chmod(0o640)
    (root / "link").symlink_to("target.txt")

    first = runner_module._tree_manifest(root)
    records = {record.path: record for record in first.records}
    assert records["target.txt"].object_type == "file"
    assert records["target.txt"].mode == 0o640
    assert records["link"].object_type == "symlink"
    assert records["link"].symlink_target == "target.txt"
    assert records["link"].digest is None

    target.chmod(0o600)
    assert runner_module._tree_manifest(root).digest != first.digest


def test_source_copy_rebind_executes_changed_copy_and_preserves_original(
    tmp_path: Path,
) -> None:
    original, original_digest = _release_shaped_candidate(tmp_path)
    copied = tmp_path / "negative-release"
    runner_module._copy_release(original, copied)
    assert not (copied / ".venv").exists()
    assert not (copied / "unlisted.txt").exists()
    before = runner_module._tree_manifest(copied)

    copied_source = copied / "src/mechanical_copy_environment/release.py"
    copied_source.write_text(copied_source.read_text().replace('"baseline"', '"near-miss"'))
    after = runner_module._rebind_release_copy(copied)
    verify_release(copied)

    probe = tmp_path / "public_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    assert environment.reset()['branch'] == 'near-miss'\n"
        "    environment.close()\n"
    )
    journal_path = tmp_path / "source-copy.journal.jsonl"
    runner_module._run_public_probe(
        probe,
        copied,
        tmp_path / "instances",
        "negative-source-copy",
        journal_path,
        "negative-source-copy",
    )
    executed_tree = runner_module._tree_manifest(copied)
    assert executed_tree.digest == after.digest
    assert not any("__pycache__" in record.path for record in executed_tree.records)
    journal = _load_host_journal(journal_path, "negative-source-copy")
    instance = tmp_path / "instances"
    instance_before = runner_module._tree_manifest(instance)
    carrier = runner_module._make_run_carrier(
        "negative-source-copy",
        copied,
        instance,
        before,
        after,
        instance_before,
        instance_before,
        journal,
        original_digest,
    )

    assert carrier.executed_copy_digest == after.digest
    assert carrier.executed_copy_digest != before.digest
    assert compute_candidate_digest(original) == original_digest
    assert (
        'BRANCH = "baseline"'
        in (original / "src/mechanical_copy_environment/release.py").read_text()
    )


def test_private_runner_records_each_fresh_environment_open(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "reopen_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    first = session.open('case')\n"
        "    first.reset()\n"
        "    first.close()\n"
        "    second = session.open('case')\n"
        "    second.invoke('branch', {})\n"
        "    second.close()\n"
    )
    journal_path = tmp_path / "reopen.journal.jsonl"

    runner_module._run_public_probe(
        probe,
        release,
        tmp_path / "reopen-instances",
        "reopen",
        journal_path,
        "baseline",
    )

    journal = _load_host_journal(journal_path, "reopen")
    assert [event.operation for event in journal.events] == [
        "open",
        "reset",
        "close",
        "open",
        "invoke",
        "close",
    ]
    assert [event.result for event in journal.events if event.operation == "open"] == [
        {"attached": True},
        {"attached": True},
    ]


def test_candidate_runtime_cannot_read_qualifier_probe_from_python_frames(
    tmp_path: Path,
) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            "    def reset(self, start=None):\n"
            "        import inspect\n"
            "        frame = inspect.currentframe()\n"
            "        while frame is not None:\n"
            "            if 'PROBE_FRAME_SENTINEL' in repr(frame.f_locals):\n"
            "                return {'branch': 'leaked'}\n"
            "            frame = frame.f_back\n"
            "        return {'branch': BRANCH}\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "frame_probe.py"
    probe.write_text(
        "# PROBE_FRAME_SENTINEL\n"
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    assert environment.reset()['branch'] == 'baseline'\n"
        "    environment.close()\n"
    )
    journal_path = tmp_path / "frame.journal.jsonl"

    runner_module._run_public_probe(
        probe,
        release,
        tmp_path / "frame-instances",
        "frame-isolation",
        journal_path,
        "baseline",
    )

    journal = _load_host_journal(journal_path, "frame-isolation")
    assert journal.events[1].result == {"branch": "baseline"}


def test_candidate_stdout_cannot_corrupt_private_actor_transport(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            "    def reset(self, start=None):\n"
            "        print('candidate-noise')\n"
            "        return {'branch': BRANCH}\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "stdout_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    assert environment.reset()['branch'] == 'baseline'\n"
        "    environment.close()\n"
    )
    journal_path = tmp_path / "stdout.journal.jsonl"

    runner_module._run_public_probe(
        probe,
        release,
        tmp_path / "stdout-instances",
        "stdout-isolation",
        journal_path,
        "baseline",
    )

    journal = _load_host_journal(journal_path, "stdout-isolation")
    assert [event.operation for event in journal.events] == ["open", "reset", "close"]


def test_candidate_named_environment_contract_error_remains_candidate_owned(
    tmp_path: Path,
) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            "    def reset(self, start=None):\n"
            "        error = type('EnvironmentContractError', (Exception,), {})\n"
            "        raise error('candidate-controlled name')\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "named_error_probe.py"
    probe.write_text(
        "def run(session, mode):\n    environment = session.open('case')\n    environment.reset()\n"
    )
    journal_path = tmp_path / "named-error.journal.jsonl"

    with pytest.raises(runner_module.CandidateExecutionFailure) as caught:
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "named-error-instances",
            "named-error",
            journal_path,
            "baseline",
        )

    assert caught.value.error_type == "EnvironmentRuntimeError"
    journal = _load_host_journal(journal_path, "named-error")
    assert journal.events[-1].result["host_exception"]["type"] == "EnvironmentRuntimeError"


def test_probe_return_with_open_handle_is_rejected_and_child_reaped(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            "    def reset(self, start=None):\n"
            "        import os\n"
            "        (self.instance / 'candidate.pid').write_text(str(os.getpid()))\n"
            "        return {'branch': BRANCH}\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "unclosed_probe.py"
    probe.write_text(
        "def run(session, mode):\n    environment = session.open('case')\n    environment.reset()\n"
    )
    instances = tmp_path / "unclosed-instances"

    with pytest.raises(RuntimeError, match="active environment handles"):
        runner_module._run_public_probe(
            probe,
            release,
            instances,
            "unclosed",
            tmp_path / "unclosed.journal.jsonl",
            "baseline",
        )

    candidate_pid = int((instances / "case/candidate.pid").read_text())
    assert not Path(f"/proc/{candidate_pid}").exists()


def test_public_probe_cannot_inject_a_host_journal_record(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "journal_forgery_probe.py"
    probe.write_text(
        "import json\n"
        "def run(session, mode):\n"
        "    session._client._wire.write(json.dumps({\n"
        "        'run_id': 'forged', 'seq': 1, 'instance': 'case',\n"
        "        'operation': 'reset', 'arguments': {'start': None},\n"
        "        'result': {'forged': True},\n"
        "    }) + '\\n')\n"
        "    session._client._wire.flush()\n"
    )
    journal_path = tmp_path / "forgery.journal.jsonl"

    with pytest.raises(runner_module.RunnerInfrastructureFailure, match="invalid call"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "forgery-instances",
            "real-run-id",
            journal_path,
            "baseline",
        )

    assert journal_path.read_bytes() == b""


def test_candidate_transport_failure_survives_host_validation_as_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    original_call = runner_module._CandidateActorTransport.call

    def fail_reset(transport: Any, operation: str, arguments: dict[str, Any]) -> Any:
        if operation == "reset":
            raise runner_module.RunnerInfrastructureFailure("transport sentinel")
        return original_call(transport, operation, arguments)

    monkeypatch.setattr(runner_module._CandidateActorTransport, "call", fail_reset)
    probe = tmp_path / "transport_failure_probe.py"
    probe.write_text(
        "def run(session, mode):\n    environment = session.open('case')\n    environment.reset()\n"
    )
    journal_path = tmp_path / "transport-failure.journal.jsonl"

    with pytest.raises(runner_module.RunnerInfrastructureFailure, match="transport sentinel"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "transport-failure-instances",
            "transport-failure",
            journal_path,
            "baseline",
        )

    journal = _load_host_journal(journal_path, "transport-failure")
    assert journal.events[-1].result == {
        "host_infrastructure_exception": {"type": "RunnerInfrastructureFailure"}
    }


def test_candidate_close_timeout_kills_and_reaps_actor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner_module, "_CHILD_TIMEOUT_SECONDS", 0.05)
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            "    def close(self):\n        return None\n",
            "    def close(self):\n"
            "        import os, subprocess, threading, time\n"
            "        (self.instance / 'close.pid').write_text(str(os.getpid()))\n"
            "        child = subprocess.Popen(['sleep', '30'])\n"
            "        (self.instance / 'descendant.pid').write_text(str(child.pid))\n"
            "        threading.Thread(target=lambda: time.sleep(30), daemon=False).start()\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "close_timeout_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    environment.reset()\n"
        "    environment.close()\n"
    )
    instances = tmp_path / "close-timeout-instances"
    journal_path = tmp_path / "close-timeout.journal.jsonl"

    with pytest.raises(
        runner_module.RunnerInfrastructureFailure,
        match="did not exit after close",
    ):
        runner_module._run_public_probe(
            probe,
            release,
            instances,
            "close-timeout",
            journal_path,
            "baseline",
        )

    actor_pid = int((instances / "case/close.pid").read_text())
    descendant_pid = int((instances / "case/descendant.pid").read_text())
    assert not Path(f"/proc/{actor_pid}").exists()
    assert not Path(f"/proc/{descendant_pid}").exists()
    journal = _load_host_journal(journal_path, "close-timeout")
    assert journal.events[-1].result == {
        "host_infrastructure_exception": {"type": "RunnerInfrastructureFailure"}
    }


def test_public_process_timeout_kills_descendant_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    program = (
        "import pathlib,subprocess,time; "
        "child=subprocess.Popen(['sleep','30']); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        qualification_module._run_public_process_group(
            (sys.executable, "-c", program),
            tmp_path,
            dict(os.environ),
            None,
            0.2,
        )

    child_pid = int(child_pid_path.read_text())
    for _ in range(50):
        if not Path(f"/proc/{child_pid}").exists():
            break
        time.sleep(0.01)
    assert not Path(f"/proc/{child_pid}").exists()


def test_private_runner_rejects_old_closed_wrapper_after_fresh_open(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "stale_wrapper_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    first = session.open('case')\n"
        "    first.reset()\n"
        "    first.close()\n"
        "    session.open('case')\n"
        "    first.invoke('branch', {})\n"
    )
    journal_path = tmp_path / "stale-wrapper.journal.jsonl"

    with pytest.raises(RuntimeError, match="closed environment handle"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "stale-wrapper-instances",
            "stale-wrapper",
            journal_path,
            "baseline",
        )

    journal = _load_host_journal(journal_path, "stale-wrapper")
    assert [event.operation for event in journal.events] == [
        "open",
        "reset",
        "close",
        "open",
    ]


def test_private_runner_rejects_concurrent_handles_for_one_instance(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "concurrent_wrapper_probe.py"
    probe.write_text(
        "def run(session, mode):\n    session.open('case')\n    session.open('case')\n"
    )
    journal_path = tmp_path / "concurrent-wrapper.journal.jsonl"

    with pytest.raises(RuntimeError, match="already has an active environment handle"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "concurrent-wrapper-instances",
            "concurrent-wrapper",
            journal_path,
            "baseline",
        )

    journal = _load_host_journal(journal_path, "concurrent-wrapper")
    assert [event.operation for event in journal.events] == ["open"]


def test_invalid_probe_reset_start_remains_qualifier_owned(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            "    def reset(self, start=None):\n"
            "        (self.instance / 'invalid-reset-reached').write_text('bad')\n"
            "        return {'branch': BRANCH}\n",
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "invalid_start_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    environment.reset({'unexpected': 1})\n"
    )
    journal_path = tmp_path / "invalid-start.journal.jsonl"

    with pytest.raises(EnvironmentContractError, match="invalid reset start"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "invalid-start-instances",
            "invalid-start",
            journal_path,
            "baseline",
        )

    journal = _load_host_journal(journal_path, "invalid-start")
    assert [event.operation for event in journal.events] == ["open", "reset"]
    assert journal.events[-1].result["host_exception"]["type"] == "EnvironmentContractError"
    assert not (tmp_path / "invalid-start-instances/case/invalid-reset-reached").exists()


def test_non_object_probe_reset_reaches_host_contract_not_transport(
    tmp_path: Path,
) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "non_object_start_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    environment.reset([])\n"
    )
    journal_path = tmp_path / "non-object-start.journal.jsonl"

    with pytest.raises(EnvironmentContractError, match="must be a JSON object"):
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "non-object-start-instances",
            "non-object-start",
            journal_path,
            "baseline",
        )

    journal = _load_host_journal(journal_path, "non-object-start")
    assert journal.events[-1].arguments == {"start": []}
    assert journal.events[-1].result["host_exception"]["type"] == "EnvironmentContractError"


def test_invalid_invoke_types_return_host_contract_observation(tmp_path: Path) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    probe = tmp_path / "invalid_invoke_types_probe.py"
    probe.write_text(
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    observation = environment.invoke(7, [])\n"
        "    assert observation['error']['code'] == 'contract.invalid_arguments'\n"
        "    environment.close()\n"
    )
    journal_path = tmp_path / "invalid-invoke-types.journal.jsonl"

    runner_module._run_public_probe(
        probe,
        release,
        tmp_path / "invalid-invoke-types-instances",
        "invalid-invoke-types",
        journal_path,
        "baseline",
    )

    journal = _load_host_journal(journal_path, "invalid-invoke-types")
    invoke = next(event for event in journal.events if event.operation == "invoke")
    assert invoke.arguments == {"tool_name": 7, "arguments": []}
    assert invoke.result["error"]["code"] == "contract.invalid_arguments"


def test_native_reader_mutation_is_rejected(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    instance.mkdir()
    state = instance / "state.bin"
    state.write_bytes(b"before")
    before = runner_module._tree_manifest(instance)
    state.write_bytes(b"after")

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._verify_native_reader_immutability([(instance, before)])
    assert caught.value.code == "native_reader_mutated_state"


def test_public_probe_candidate_exit_is_attributed_to_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        qualification_module,
        "_run_public_process_group",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=20,
            stdout="",
            stderr=(
                '{"error_type":"EnvironmentRuntimeError",'
                '"message":"PRIVATE_PROBE_PATH/public_probe.py"}'
            ),
        ),
    )
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._run(
            ("candidate-python",),
            tmp_path,
            {},
            QualificationConfig(),
            "public_probe:baseline-test-run",
        )
    assert caught.value.phase == "candidate_execution"
    assert caught.value.code == "candidate_runtime_failed"
    assert caught.value.candidate_finding is not None
    assert caught.value.candidate_finding.contract_clause == "public_environment_runtime"
    assert caught.value.candidate_finding.runtime_error == "EnvironmentRuntimeError"
    assert "PRIVATE_PROBE_PATH" not in json.dumps(caught.value.candidate_finding.to_document())


def test_probe_contract_exit_is_not_attributed_to_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        qualification_module,
        "_run_public_process_group",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=21,
            stdout="",
            stderr=('{"error_type":"EnvironmentContractError","message":"invalid reset start"}'),
        ),
    )

    with pytest.raises(QualificationFailure) as caught:
        qualification_module._run(
            ("candidate-python",),
            tmp_path,
            {},
            QualificationConfig(),
            "public_probe:baseline-test-run",
        )

    assert caught.value.phase == "probe_execution"
    assert caught.value.code == "probe_execution_failed"
    assert caught.value.candidate_finding is None


def test_qualifier_prompt_forbids_unrelated_fallback_and_aggregate_assertions() -> None:
    prompt = qualification_module._PROBE_PROMPT
    assert "must occur exactly once" in prompt
    assert "never fall back" in prompt
    assert "matching acceptance assertion" in prompt
    assert "exact public call sequences and named instance" in prompt
    assert "call session.open again with the same instance name" in prompt
    assert "reusing a closed object" in prompt


def test_negative_copy_candidate_exit_is_attributed_to_qualifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        qualification_module,
        "_run_public_process_group",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=20,
            stdout="",
            stderr='{"error_type":"EnvironmentRuntimeError","message":"bad near miss"}',
        ),
    )
    with pytest.raises(QualificationFailure) as caught:
        qualification_module._run(
            ("candidate-python",),
            tmp_path,
            {},
            QualificationConfig(),
            "public_probe:negative-012",
        )
    assert caught.value.phase == "probe_execution"
    assert caught.value.code == "negative_public_runtime_failed"


def test_private_runner_attributes_real_environment_crash_to_candidate(
    tmp_path: Path,
) -> None:
    release, _ = _release_shaped_candidate(tmp_path)
    source = release / "src/mechanical_copy_environment/release.py"
    source.write_text(
        source.read_text().replace(
            'return {"branch": BRANCH}',
            'raise RuntimeError("candidate boom")',
            1,
        )
    )
    runner_module._rebind_release_copy(release)
    probe = tmp_path / "crash_probe.py"
    probe.write_text(
        "def run(session, mode):\n    environment = session.open('case')\n    environment.reset()\n"
    )
    journal = tmp_path / "crash.journal.jsonl"
    with pytest.raises(runner_module.CandidateExecutionFailure) as caught:
        runner_module._run_public_probe(
            probe,
            release,
            tmp_path / "crash-instances",
            "candidate-crash",
            journal,
            "baseline",
        )

    assert caught.value.error_type == "EnvironmentRuntimeError"
    assert str(caught.value) == "reset failed: candidate boom"


def test_real_candidate_sandbox_runs_baseline_and_negative_without_private_leaks(
    tmp_path: Path,
) -> None:
    if os.environ.get("RUN_CODEX_SANDBOX_INTEGRATION") != "1":
        pytest.skip("set RUN_CODEX_SANDBOX_INTEGRATION=1 outside an existing sandbox")
    candidate, _ = _release_shaped_candidate(tmp_path)
    qualification = tmp_path / "qualification"
    qualification.mkdir()
    runtime = qualification / "runtime"
    runtime.mkdir()
    executions = runtime / "executions"
    executions.mkdir()
    baseline_root = executions / "67f3d9d55b51470e8f213ee83e3fcb51"
    baseline_instances = baseline_root / "instances"
    negative_root = executions / "e0a6f4573ef5460399eef715a06bfc73"
    negative_instances = negative_root / "instances"
    sibling_home = tmp_path / "qualification-codex-home"
    sibling_home.mkdir()
    sibling_secret = sibling_home / "hidden-verifier-context.txt"
    sibling_secret.write_text("hidden verifier context")
    dependencies = runtime / "loader-deps"
    dependencies.mkdir()
    (dependencies / "third_party_runtime.py").write_text("VALUE = 'dependency'\n")
    public_probe = qualification / "public_probe.py"
    public_probe.write_text(
        "from pathlib import Path\n"
        "def run(session, mode):\n"
        f"    for root in ({str(baseline_instances)!r}, {str(negative_instances)!r}):\n"
        "        try:\n"
        "            (Path(root) / 'probe-forgery').write_text('forged')\n"
        "        except OSError:\n"
        "            pass\n"
        "        else:\n"
        "            raise AssertionError('public probe can mutate the Candidate instance')\n"
        "    environment = session.open('case')\n"
        "    sibling = session.open('other')\n"
        "    expected = 'baseline:dependency' if mode == 'baseline' else 'near-miss:dependency'\n"
        "    assert environment.reset()['branch'] == expected\n"
        "    assert sibling.reset()['branch'] == expected\n"
        "    environment.close()\n"
        "    sibling.close()\n"
    )
    original_leak = candidate / ".venv/qualification-leak.txt"
    external_leak = Path(f"/tmp/foundry-candidate-leak-{tmp_path.name}")
    external_leak.unlink(missing_ok=True)
    source = candidate / "src/mechanical_copy_environment/release.py"
    original_source = source
    replacement = (
        "    def reset(self, start=None):\n"
        "        import os\n"
        "        from pathlib import Path\n"
        "        (self.instance / 'actor.pid').write_text(str(os.getpid()))\n"
        "        sibling_name = 'other' if self.instance.name == 'case' else 'case'\n"
        "        try:\n"
        "            target = self.instance.parent / sibling_name / 'cross-instance-forgery'\n"
        "            target.write_text('bad')\n"
        "        except OSError:\n"
        "            pass\n"
        "        else:\n"
        "            return {'branch': 'leaked-cross-instance'}\n"
        "        try:\n"
        "            parent = Path(f'/proc/{os.getppid()}')\n"
        "            metadata = (parent / 'cmdline').read_bytes()\n"
        "            metadata += (parent / 'environ').read_bytes()\n"
        "        except OSError:\n"
        "            metadata = b''\n"
        "        if any(value in metadata for value in "
        "(b'baseline-sandbox', b'negative-sandbox', b'near-miss:dependency')):\n"
        "            return {'branch': 'leaked-parent-metadata'}\n"
        f"        for target in ({str(original_leak)!r}, {str(external_leak)!r}):\n"
        "            try:\n"
        "                Path(target).write_text('leak')\n"
        "            except OSError:\n"
        "                pass\n"
        "            else:\n"
        "                return {'branch': 'leaked-write'}\n"
        "        try:\n"
        f"            Path({str(public_probe)!r}).read_text()\n"
        "        except OSError:\n"
        "            pass\n"
        "        else:\n"
        "            return {'branch': 'leaked-probe'}\n"
        "        try:\n"
        f"            Path({str(original_source)!r}).read_text()\n"
        "        except OSError:\n"
        "            pass\n"
        "        else:\n"
        "            return {'branch': 'leaked-original-source'}\n"
        "        try:\n"
        f"            Path({str(sibling_secret)!r}).read_text()\n"
        "        except OSError:\n"
        "            pass\n"
        "        else:\n"
        "            return {'branch': 'leaked-sibling-context'}\n"
        "        import third_party_runtime\n"
        "        return {'branch': BRANCH + ':' + third_party_runtime.VALUE}\n"
    )
    source.write_text(
        source.read_text().replace(
            '    def reset(self, start=None):\n        return {"branch": BRANCH}\n',
            replacement,
            1,
        )
    )
    runner_module._rebind_release_copy(candidate)
    candidate_python = candidate / ".venv/bin/python"
    candidate_python.parent.mkdir(parents=True, exist_ok=True)
    candidate_python.symlink_to(sys.executable)
    bundle = qualification_module.ProbeBundle(qualification, (), "b" * 64)
    config = QualificationConfig(uv_cache_dir=tmp_path / "uv-cache")
    baseline_release = baseline_root / "release"
    runner_module._copy_release(candidate, baseline_release)
    baseline_instances.mkdir()
    baseline = qualification_module._execute_public_probe(
        candidate_python,
        candidate,
        baseline_release,
        baseline_instances,
        "baseline-sandbox",
        baseline_root / "journal.jsonl",
        "baseline",
        bundle,
        dependencies,
        qualification_module._clean_env(config),
        config,
    )

    negative_release = negative_root / "release"
    runner_module._copy_release(candidate, negative_release)
    negative_source = negative_release / "src/mechanical_copy_environment/release.py"
    negative_source.write_text(negative_source.read_text().replace('"baseline"', '"near-miss"', 1))
    runner_module._rebind_release_copy(negative_release)
    negative_instances.mkdir()
    negative = qualification_module._execute_public_probe(
        candidate_python,
        candidate,
        negative_release,
        negative_instances,
        "negative-sandbox",
        negative_root / "journal.jsonl",
        "negative",
        bundle,
        dependencies,
        qualification_module._clean_env(config),
        config,
    )

    assert [event.result for event in baseline.events if event.operation == "reset"] == [
        {"branch": "baseline:dependency"},
        {"branch": "baseline:dependency"},
    ]
    assert [event.result for event in negative.events if event.operation == "reset"] == [
        {"branch": "near-miss:dependency"},
        {"branch": "near-miss:dependency"},
    ]
    assert not original_leak.exists()
    assert not external_leak.exists()

    public_probe.write_text(
        "import time\n"
        "def run(session, mode):\n"
        "    environment = session.open('case')\n"
        "    environment.reset()\n"
        "    time.sleep(30)\n"
    )
    timeout_root = executions / "069472bc48a14905be8d17bc9814c75c"
    timeout_release = timeout_root / "release"
    runner_module._copy_release(candidate, timeout_release)
    timeout_instances = timeout_root / "instances"
    timeout_instances.mkdir()
    timeout_config = QualificationConfig(
        command_timeout_seconds=0.5,
        uv_cache_dir=tmp_path / "uv-cache",
    )
    with pytest.raises(QualificationFailure) as timeout:
        qualification_module._execute_public_probe(
            candidate_python,
            candidate,
            timeout_release,
            timeout_instances,
            "timeout-sandbox",
            timeout_root / "journal.jsonl",
            "baseline",
            bundle,
            dependencies,
            qualification_module._clean_env(timeout_config),
            timeout_config,
        )

    assert timeout.value.phase == "infrastructure"
    assert timeout.value.code == "probe_process_failed"
    timeout_marker = str(timeout_root).encode()

    def matching_processes() -> list[int]:
        matches: list[int] = []
        for process in Path("/proc").iterdir():
            if not process.name.isdigit():
                continue
            try:
                command = (process / "cmdline").read_bytes()
            except OSError:
                continue
            if timeout_marker in command:
                matches.append(int(process.name))
        return matches

    for _ in range(50):
        if not matching_processes():
            break
        time.sleep(0.01)
    assert matching_processes() == []

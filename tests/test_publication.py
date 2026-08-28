"""Mechanical Slice 5 package tests; these fixtures never claim a real release."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agent_env_foundry.builder import compute_candidate_digest
from agent_env_foundry.publication import (
    PublicationError,
    assemble_environment_release,
    extract_release_zip,
    publish_environment_release,
    verify_environment_release,
    write_release_zip,
)
from agent_env_foundry.qualification import EvidenceRow, QualificationResult
from release_factory import build_release


def _candidate(tmp_path: Path) -> Path:
    root = build_release(tmp_path / "candidate")
    (root / "README.md").write_text("# Mechanical environment\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname="mechanical-environment"\nversion="0.1.0"\n'
    )
    (root / "uv.lock").write_text("version = 1\n")
    (root / "tests").mkdir()
    (root / "tests/test_mechanical.py").write_text("def test_mechanical(): assert True\n")
    package = root / "src/mechanical_environment"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def make_environment(instance_dir): return instance_dir\n"
    )
    (package / "seed.json").write_text('{"ready":true}\n')
    descriptor = json.loads((root / "release.json").read_text())
    descriptor["environment_factory"] = "mechanical_environment:make_environment"
    (root / "release.json").write_text(json.dumps(descriptor))
    (root / "dist").mkdir()
    with zipfile.ZipFile(root / "dist/mechanical_environment-0.1.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr(
            "mechanical_environment/__init__.py",
            (package / "__init__.py").read_bytes(),
        )
        wheel.writestr("mechanical_environment/seed.json", (package / "seed.json").read_bytes())
        wheel.writestr("mechanical_environment-0.1.0.dist-info/RECORD", "")
    (root / "dist/mechanical_environment-0.1.0.tar.gz").write_bytes(b"sdist")
    (root / "BUILDER_PROJECTION.json").write_text('{"private":true}')
    (root / "ENVIRONMENT_CONTRACT.md").write_text("private contract")
    return root


def _qualification(candidate: Path, *, status: str = "passed") -> QualificationResult:
    row_document = {
        "requirement_id": "REQ-001",
        "relation_digest": "1" * 64,
        "public_calls": [
            {
                "seq": 1,
                "instance": "mechanical",
                "tool_name": "act",
                "arguments": {},
                "observation": {"ok": True, "data": {}, "error": None},
            }
        ],
        "native_observations": [{"mechanical": True}],
        "assertions": [
            {
                "assertion_id": "assertion-1",
                "passed": True,
                "covers": ["native_before_after"],
                "actual": True,
                "expected": True,
            }
        ],
        "source_use": {},
    }
    row = EvidenceRow("REQ-001", "1" * 64, row_document)
    return QualificationResult(
        status=status,  # type: ignore[arg-type]
        candidate_digest=compute_candidate_digest(candidate),
        expected_relations_digest="2" * 64,
        evidence_digest="3" * 64,
        evidence_rows=(row,),
        probe_bundle_digest="4" * 64,
        negative_evidence_count=1,
    )


def test_host_assembles_and_verifies_non_circular_release(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    release = assemble_environment_release(
        candidate,
        _qualification(candidate),
        "# Accepted mechanical Brief\n",
        tmp_path / "assembled",
    )

    verified = verify_environment_release(release.root)
    descriptor = json.loads((release.root / "release.json").read_text())
    qualification = json.loads((release.root / "qualification.json").read_text())
    assert verified.release_id == release.release_id
    assert len(release.release_id) == 64
    assert qualification["payload_digest"] == descriptor["payload_digest"]
    assert qualification["verdict"] == "passed"
    assert qualification["requirement_evidence"] == [
        {
            "requirement_id": "REQ-001",
            "relation_digest": "1" * 64,
            "evidence_digest": qualification["requirement_evidence"][0]["evidence_digest"],
        }
    ]
    assert not (release.root / "project/BUILDER_PROJECTION.json").exists()
    assert not (release.root / "project/ENVIRONMENT_CONTRACT.md").exists()
    assert (release.root / "dist/mechanical_environment-0.1.0-py3-none-any.whl").is_file()


def test_archive_relocates_and_reverifies_exact_identity(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    release = assemble_environment_release(
        candidate, _qualification(candidate), "# Brief\n", tmp_path / "assembled"
    )
    archive = tmp_path / "release.zip"
    first_digest = write_release_zip(release.root, archive)
    extracted = extract_release_zip(archive, tmp_path / "relocated")
    assert extracted.release_id == release.release_id
    assert len(first_digest) == 64


def test_tampered_payload_and_qualification_fail_closed(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    release = assemble_environment_release(
        candidate, _qualification(candidate), "# Brief\n", tmp_path / "assembled"
    )
    (release.root / "docs/ENVIRONMENT.md").write_text("tampered")
    with pytest.raises(PublicationError) as payload:
        verify_environment_release(release.root)
    assert payload.value.code == "payload_record_mismatch"

    candidate = _candidate(tmp_path / "second")
    other = assemble_environment_release(
        candidate, _qualification(candidate), "# Brief\n", tmp_path / "other"
    )
    (other.root / "qualification.json").write_text("{}")
    with pytest.raises(PublicationError) as qualification:
        verify_environment_release(other.root)
    assert qualification.value.code == "qualification_digest_mismatch"


def test_release_metadata_must_be_canonical_bytes(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    release = assemble_environment_release(
        candidate, _qualification(candidate), "# Brief\n", tmp_path / "assembled"
    )
    descriptor = json.loads((release.root / "release.json").read_text())
    (release.root / "release.json").write_text(json.dumps(descriptor, indent=2))

    with pytest.raises(PublicationError) as caught:
        verify_environment_release(release.root)

    assert caught.value.code == "release_descriptor_not_canonical"


def test_built_wheel_must_contain_exact_generated_package_data(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    wheel_path = next((candidate / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(
            "mechanical_environment/__init__.py",
            (candidate / "src/mechanical_environment/__init__.py").read_bytes(),
        )
        wheel.writestr("mechanical_environment-0.1.0.dist-info/RECORD", "")

    with pytest.raises(PublicationError) as caught:
        assemble_environment_release(
            candidate, _qualification(candidate), "# Brief\n", tmp_path / "assembled"
        )

    assert caught.value.code == "distribution_project_mismatch"


def test_unqualified_candidate_cannot_be_assembled(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    with pytest.raises(PublicationError) as caught:
        assemble_environment_release(
            candidate,
            _qualification(candidate, status="probe_defect"),
            "# Brief\n",
            tmp_path / "assembled",
        )
    assert caught.value.code == "qualification_not_passed"


def test_local_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    assembled = assemble_environment_release(
        candidate, _qualification(candidate), "# Brief\n", tmp_path / "assembled"
    )
    first = publish_environment_release(assembled.root, tmp_path / "store")
    second = publish_environment_release(assembled.root, tmp_path / "store")
    assert first.release_id == second.release_id
    assert first.archive is not None and first.archive.is_file()
    assert first.root.stat().st_mode & 0o222 == 0

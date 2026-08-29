"""Immutable S1 EnvironmentRelease assembly, verification, ZIP, and publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agent_env_foundry.builder import candidate_files, compute_candidate_digest
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.qualification import (
    QualificationConfig,
    QualificationResult,
    replay_qualification,
)
from agent_env_foundry.release import (
    canonical_bytes,
    parse_manifest,
    safe_member_path,
    verify_release,
)
from agent_env_foundry.research import BuilderProjection

RELEASE_FORMAT = "environment-package/1"
QUALIFICATION_FORMAT = "environment-qualification/1"
DESCRIPTOR_NAME = "release.json"
MANIFEST_NAME = "payload-manifest.json"
QUALIFICATION_NAME = "qualification.json"
PROJECT_ROOT = PurePosixPath("project")
RELEASE_KEYS = frozenset(
    {
        "format",
        "canonicalization",
        "hash",
        "payload_manifest",
        "payload_digest",
        "qualification",
        "qualification_digest",
        "project_root",
        "candidate_descriptor",
        "public_brief",
        "public_environment_docs",
    }
)
QUALIFICATION_KEYS = frozenset(
    {
        "format",
        "verdict",
        "payload_digest",
        "candidate_digest",
        "expected_relations_digest",
        "probe_bundle_digest",
        "evidence_digest",
        "requirement_ids",
        "requirement_evidence",
        "positive_evidence_count",
        "negative_evidence_count",
    }
)
ROOT_MEMBERS = frozenset(
    {
        DESCRIPTOR_NAME,
        MANIFEST_NAME,
        QUALIFICATION_NAME,
        "project",
        "dist",
        "docs",
        "licenses",
    }
)


class PublicationError(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


@dataclass(frozen=True)
class EnvironmentRelease:
    release_id: str
    root: Path
    project_root: Path
    payload_digest: str
    qualification_digest: str
    archive: Path | None = None


@dataclass(frozen=True)
class ColdReleaseConfig:
    uv_cache_dir: Path = Path("/tmp/agent-env-foundry-cold-uv-cache")
    command_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")


@dataclass(frozen=True)
class ColdVerification:
    release: EnvironmentRelease
    runtime_project: Path
    qualification: QualificationResult


def assemble_environment_release(
    candidate_root: Path,
    qualification: QualificationResult,
    development_brief: str,
    destination: Path,
) -> EnvironmentRelease:
    """Assemble one qualified Candidate into a fresh release directory."""
    candidate = Path(candidate_root).resolve()
    root = Path(destination)
    _require_fresh_directory(root)
    _validate_qualification(qualification, candidate)
    if not isinstance(development_brief, str) or not development_brief.strip():
        raise PublicationError(
            "assembly", "development_brief_missing", "A non-empty accepted Brief is required"
        )

    project = root / PROJECT_ROOT
    project.mkdir()
    for source in candidate_files(candidate):
        relative = source.relative_to(candidate)
        _copy_regular(source, project / relative)

    dist = root / "dist"
    dist.mkdir()
    candidate_dist = candidate / "dist"
    if not candidate_dist.is_dir():
        raise PublicationError("assembly", "distribution_missing", "Candidate dist/ is missing")
    distributions = sorted(candidate_dist.iterdir(), key=lambda path: path.name)
    if not distributions or any(path.is_symlink() or not path.is_file() for path in distributions):
        raise PublicationError(
            "assembly", "distribution_invalid", "Candidate dist/ must contain regular files"
        )
    for source in distributions:
        _copy_regular(source, dist / source.name)

    docs = root / "docs"
    docs.mkdir()
    (docs / "DEVELOPMENT_BRIEF.md").write_text(development_brief, encoding="utf-8")
    readme = candidate / "README.md"
    if not readme.is_file() or readme.is_symlink():
        raise PublicationError(
            "assembly", "environment_docs_missing", "Candidate README is missing"
        )
    (docs / "ENVIRONMENT.md").write_bytes(readme.read_bytes())

    licenses = root / "licenses"
    licenses.mkdir()
    (licenses / "NOTICE.txt").write_text(
        "The generated project's dependency declarations are in project/pyproject.toml "
        "and project/uv.lock.\n"
        "Any project license files remain in project/. This notice does not grant "
        "redistribution rights.\n",
        encoding="utf-8",
    )

    _verify_built_distribution(candidate, distributions)

    records = _payload_records(root)
    manifest_document = {"files": records}
    payload_digest = _sha256(canonical_bytes(manifest_document))
    (root / MANIFEST_NAME).write_bytes(canonical_bytes(manifest_document))

    requirement_ids = [row.requirement_id for row in qualification.evidence_rows]
    requirement_evidence = [
        {
            "requirement_id": row.requirement_id,
            "relation_digest": row.relation_digest,
            "evidence_digest": _sha256(canonical_bytes(row.document)),
        }
        for row in qualification.evidence_rows
    ]
    qualification_document = {
        "format": QUALIFICATION_FORMAT,
        "verdict": "passed",
        "payload_digest": payload_digest,
        "candidate_digest": qualification.candidate_digest,
        "expected_relations_digest": qualification.expected_relations_digest,
        "probe_bundle_digest": qualification.probe_bundle_digest,
        "evidence_digest": qualification.evidence_digest,
        "requirement_ids": requirement_ids,
        "requirement_evidence": requirement_evidence,
        "positive_evidence_count": len(requirement_ids),
        "negative_evidence_count": qualification.negative_evidence_count,
    }
    qualification_bytes = canonical_bytes(qualification_document)
    qualification_digest = _sha256(qualification_bytes)
    (root / QUALIFICATION_NAME).write_bytes(qualification_bytes)

    descriptor = {
        "format": RELEASE_FORMAT,
        "canonicalization": "rfc8785",
        "hash": "sha256",
        "payload_manifest": MANIFEST_NAME,
        "payload_digest": payload_digest,
        "qualification": QUALIFICATION_NAME,
        "qualification_digest": qualification_digest,
        "project_root": str(PROJECT_ROOT),
        "candidate_descriptor": "project/release.json",
        "public_brief": "docs/DEVELOPMENT_BRIEF.md",
        "public_environment_docs": "docs/ENVIRONMENT.md",
    }
    descriptor_bytes = canonical_bytes(descriptor)
    (root / DESCRIPTOR_NAME).write_bytes(descriptor_bytes)
    release = verify_environment_release(root)
    expected_id = _sha256(descriptor_bytes)
    if release.release_id != expected_id:
        raise PublicationError("assembly", "release_identity_mismatch", "Release ID drifted")
    return release


def verify_environment_release(root: Path) -> EnvironmentRelease:
    release_root = Path(root).resolve()
    if not release_root.is_dir() or release_root.is_symlink():
        raise PublicationError("verification", "release_root_invalid", "Release root is invalid")
    actual_root_members = {path.name for path in release_root.iterdir()}
    if actual_root_members != ROOT_MEMBERS:
        raise PublicationError(
            "verification",
            "release_root_members_invalid",
            "Release root members differ from the closed format",
            expected=sorted(ROOT_MEMBERS),
            actual=sorted(actual_root_members),
        )
    descriptor_path = release_root / DESCRIPTOR_NAME
    descriptor = _read_json(descriptor_path, "release descriptor")
    if descriptor_path.read_bytes() != canonical_bytes(descriptor):
        raise PublicationError(
            "verification",
            "release_descriptor_not_canonical",
            "Release descriptor bytes are not canonical RFC 8785 JSON",
        )
    if not isinstance(descriptor, dict) or set(descriptor) != RELEASE_KEYS:
        raise PublicationError(
            "verification", "release_descriptor_invalid", "Release descriptor members are invalid"
        )
    if (
        descriptor["format"] != RELEASE_FORMAT
        or descriptor["canonicalization"] != "rfc8785"
        or descriptor["hash"] != "sha256"
    ):
        raise PublicationError(
            "verification", "release_descriptor_invalid", "Release descriptor version is invalid"
        )
    manifest_path = _bound_file(release_root, descriptor["payload_manifest"], MANIFEST_NAME)
    manifest = _read_json(manifest_path, "payload manifest")
    if manifest_path.read_bytes() != canonical_bytes(manifest):
        raise PublicationError(
            "verification",
            "payload_manifest_not_canonical",
            "Payload manifest bytes are not canonical RFC 8785 JSON",
        )
    payload_digest = _sha256(canonical_bytes(manifest))
    if payload_digest != _digest_field(descriptor["payload_digest"], "payload_digest"):
        raise PublicationError(
            "verification", "payload_digest_mismatch", "Payload manifest digest differs"
        )
    records = parse_manifest(manifest)
    listed = {record.path for record in records}
    actual_payload = {
        PurePosixPath(path.relative_to(release_root).as_posix())
        for top in ("project", "dist", "docs", "licenses")
        for path in (release_root / top).rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if listed != actual_payload:
        raise PublicationError(
            "verification",
            "payload_members_mismatch",
            "Payload manifest is not a complete file closure",
            missing=sorted(str(path) for path in actual_payload - listed),
            unbacked=sorted(str(path) for path in listed - actual_payload),
        )
    for record in records:
        path = _bound_file(release_root, str(record.path), str(record.path))
        actual_digest = _sha256(path.read_bytes())
        actual_mode = stat.S_IMODE(path.stat().st_mode)
        if actual_digest != record.digest or actual_mode != record.mode:
            raise PublicationError(
                "verification",
                "payload_record_mismatch",
                "Payload member bytes or mode differ",
                path=str(record.path),
                expected_digest=record.digest,
                actual_digest=actual_digest,
                expected_mode=record.mode,
                actual_mode=actual_mode,
            )

    qualification_path = _bound_file(release_root, descriptor["qualification"], QUALIFICATION_NAME)
    qualification_bytes = qualification_path.read_bytes()
    if _sha256(qualification_bytes) != _digest_field(
        descriptor["qualification_digest"], "qualification_digest"
    ):
        raise PublicationError(
            "verification", "qualification_digest_mismatch", "Qualification digest differs"
        )
    qualification = _read_json(qualification_path, "qualification summary")
    if qualification_bytes != canonical_bytes(qualification):
        raise PublicationError(
            "verification",
            "qualification_not_canonical",
            "Qualification summary bytes are not canonical RFC 8785 JSON",
        )
    _verify_qualification_document(qualification, payload_digest)

    project_root = _bound_directory(release_root, descriptor["project_root"], "project")
    candidate_descriptor = _bound_file(
        release_root, descriptor["candidate_descriptor"], "project/release.json"
    )
    if candidate_descriptor.parent != project_root:
        raise PublicationError(
            "verification", "candidate_descriptor_invalid", "Candidate descriptor is misplaced"
        )
    verify_release(project_root)
    candidate_digest = compute_candidate_digest(project_root)
    if candidate_digest != qualification["candidate_digest"]:
        raise PublicationError(
            "verification",
            "candidate_digest_mismatch",
            "Published project differs from Qualification",
        )
    _bound_file(release_root, descriptor["public_brief"], "docs/DEVELOPMENT_BRIEF.md")
    _bound_file(release_root, descriptor["public_environment_docs"], "docs/ENVIRONMENT.md")
    dist_files = [path for path in (release_root / "dist").iterdir() if path.is_file()]
    if not any(path.suffix == ".whl" for path in dist_files) or not any(
        path.name.endswith(".tar.gz") for path in dist_files
    ):
        raise PublicationError(
            "verification", "distribution_incomplete", "Wheel and source distribution are required"
        )
    descriptor_bytes = canonical_bytes(descriptor)
    return EnvironmentRelease(
        release_id=_sha256(descriptor_bytes),
        root=release_root,
        project_root=project_root,
        payload_digest=payload_digest,
        qualification_digest=_sha256(qualification_bytes),
    )


def write_release_zip(release_root: Path, destination: Path) -> str:
    verified = verify_environment_release(release_root)
    archive = Path(destination)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise PublicationError("archive", "archive_exists", "Archive destination must be fresh")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for path in sorted(
            verified.root.rglob("*"), key=lambda item: item.relative_to(verified.root).as_posix()
        ):
            if path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise PublicationError(
                    "archive", "archive_member_invalid", "Symlinks are forbidden"
                )
            relative = path.relative_to(verified.root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(
                info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return _sha256(archive.read_bytes())


def extract_release_zip(archive: Path, destination: Path) -> EnvironmentRelease:
    source = Path(archive)
    root = Path(destination)
    _require_fresh_directory(root)
    seen: set[PurePosixPath] = set()
    try:
        with zipfile.ZipFile(source, "r") as package:
            for info in package.infolist():
                relative = safe_member_path(info.filename, field="ZIP member")
                if relative in seen or info.is_dir():
                    raise PublicationError(
                        "extraction", "zip_member_invalid", "ZIP members are invalid"
                    )
                seen.add(relative)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise PublicationError(
                        "extraction", "zip_member_invalid", "ZIP symlinks are forbidden"
                    )
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(info))
                target.chmod(mode & 0o777)
    except zipfile.BadZipFile as exc:
        raise PublicationError(
            "extraction", "zip_invalid", "Release archive is not a valid ZIP"
        ) from exc
    return verify_environment_release(root)


def publish_environment_release(assembled_root: Path, store_root: Path) -> EnvironmentRelease:
    assembled = verify_environment_release(assembled_root)
    store = Path(store_root)
    store.mkdir(parents=True, exist_ok=True)
    target = store / assembled.release_id
    archive = store / f"{assembled.release_id}.zip"
    if target.exists():
        existing = verify_environment_release(target)
        if existing.release_id != assembled.release_id:
            raise PublicationError("publication", "release_collision", "Release ID collision")
    else:
        shutil.copytree(assembled.root, target, symlinks=False)
        _seal_tree(target)
    if archive.exists():
        with tempfile.TemporaryDirectory(prefix="release-archive-check-", dir=store) as temporary:
            extracted = extract_release_zip(archive, Path(temporary) / "release")
            if extracted.release_id != assembled.release_id:
                raise PublicationError("publication", "archive_collision", "Archive ID differs")
    else:
        temporary_archive = store / f".{assembled.release_id}.zip.tmp"
        if temporary_archive.exists():
            temporary_archive.unlink()
        write_release_zip(target, temporary_archive)
        os.replace(temporary_archive, archive)
    return EnvironmentRelease(
        release_id=assembled.release_id,
        root=target,
        project_root=target / PROJECT_ROOT,
        payload_digest=assembled.payload_digest,
        qualification_digest=assembled.qualification_digest,
        archive=archive,
    )


def cold_verify_environment_release(
    archive: Path,
    cold_root: Path,
    projection: BuilderProjection,
    probe_source_root: Path,
    *,
    config: ColdReleaseConfig | None = None,
) -> ColdVerification:
    """Relocate exact archive bytes, prepare locked dependencies, and replay Qualification."""
    if config is None:
        config = ColdReleaseConfig()
    root = Path(cold_root)
    _require_fresh_directory(root)
    release = extract_release_zip(archive, root / "release")
    runtime_project = root / "runtime-project"
    shutil.copytree(release.project_root, runtime_project, symlinks=False)
    environment = dict(os.environ)
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    environment["UV_CACHE_DIR"] = str(config.uv_cache_dir)
    try:
        prepared = subprocess.run(
            (
                "uv",
                "sync",
                "--frozen",
                "--all-groups",
                "--link-mode",
                "copy",
            ),
            cwd=runtime_project,
            env=environment,
            text=True,
            capture_output=True,
            timeout=config.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError(
            "cold_preparation",
            "cold_preparation_failed",
            "Cold uv preparation could not run",
            error=f"{type(exc).__name__}: {exc}",
        ) from exc
    if prepared.returncode:
        raise PublicationError(
            "cold_preparation",
            "cold_preparation_failed",
            "Cold uv preparation failed",
            returncode=prepared.returncode,
            stdout=prepared.stdout,
            stderr=prepared.stderr,
        )
    qualification_document = _read_json(release.root / QUALIFICATION_NAME, "qualification summary")
    candidate_digest = qualification_document["candidate_digest"]
    if compute_candidate_digest(runtime_project) != candidate_digest:
        raise PublicationError(
            "cold_preparation",
            "cold_candidate_digest_mismatch",
            "Prepared cold project differs from the qualified Candidate",
        )
    replay = replay_qualification(
        projection,
        runtime_project,
        candidate_digest,
        probe_source_root,
        root / "qualification-replay",
        config=QualificationConfig(
            command_timeout_seconds=config.command_timeout_seconds,
            turn_timeout_seconds=600.0,
        ),
    )
    if replay.status != "passed":
        raise PublicationError(
            "cold_qualification",
            "cold_qualification_failed",
            "Cold relocated project failed protected Qualification replay",
            failure_code=replay.failure_code,
            details=replay.details,
        )
    if replay.probe_bundle_digest != qualification_document["probe_bundle_digest"]:
        raise PublicationError(
            "cold_qualification",
            "cold_probe_bundle_mismatch",
            "Cold replay used different semantic probe bytes",
        )
    return ColdVerification(release, runtime_project, replay)


def _validate_qualification(qualification: QualificationResult, candidate: Path) -> None:
    if qualification.status != "passed":
        raise PublicationError("assembly", "qualification_not_passed", "Qualification must pass")
    actual_candidate = compute_candidate_digest(candidate)
    if qualification.candidate_digest != actual_candidate:
        raise PublicationError(
            "assembly", "candidate_digest_mismatch", "Qualification binds different Candidate bytes"
        )
    if (
        qualification.evidence_digest is None
        or qualification.probe_bundle_digest is None
        or not qualification.evidence_rows
        or qualification.negative_evidence_count != len(qualification.evidence_rows)
    ):
        raise PublicationError(
            "assembly", "qualification_incomplete", "Qualification evidence is incomplete"
        )
    ids = [row.requirement_id for row in qualification.evidence_rows]
    if len(ids) != len(set(ids)):
        raise PublicationError("assembly", "qualification_incomplete", "Requirement ids repeat")


def _verify_qualification_document(document: Any, payload_digest: str) -> None:
    if not isinstance(document, dict) or set(document) != QUALIFICATION_KEYS:
        raise PublicationError(
            "verification", "qualification_invalid", "Qualification summary members are invalid"
        )
    if (
        document["format"] != QUALIFICATION_FORMAT
        or document["verdict"] != "passed"
        or document["payload_digest"] != payload_digest
    ):
        raise PublicationError(
            "verification", "qualification_invalid", "Qualification summary binds wrong payload"
        )
    for field in (
        "candidate_digest",
        "expected_relations_digest",
        "probe_bundle_digest",
        "evidence_digest",
    ):
        _digest_field(document[field], field)
    ids = document["requirement_ids"]
    evidence = document["requirement_evidence"]
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(item, str) or not item for item in ids)
        or len(ids) != len(set(ids))
        or document["positive_evidence_count"] != len(ids)
        or document["negative_evidence_count"] != len(ids)
        or not isinstance(evidence, list)
        or len(evidence) != len(ids)
    ):
        raise PublicationError(
            "verification", "qualification_invalid", "Qualification coverage is incomplete"
        )
    evidence_ids: list[str] = []
    for position, item in enumerate(evidence):
        if not isinstance(item, dict) or set(item) != {
            "requirement_id",
            "relation_digest",
            "evidence_digest",
        }:
            raise PublicationError(
                "verification",
                "qualification_invalid",
                "Requirement evidence references are invalid",
                position=position,
            )
        requirement_id = item["requirement_id"]
        if not isinstance(requirement_id, str) or not requirement_id:
            raise PublicationError(
                "verification", "qualification_invalid", "Requirement evidence id is invalid"
            )
        evidence_ids.append(requirement_id)
        _digest_field(item["relation_digest"], "relation_digest")
        _digest_field(item["evidence_digest"], "evidence_digest")
    if evidence_ids != ids:
        raise PublicationError(
            "verification",
            "qualification_invalid",
            "Requirement evidence order differs from requirement coverage",
        )


def _verify_built_distribution(candidate: Path, distributions: list[Path]) -> None:
    wheels = [path for path in distributions if path.suffix == ".whl"]
    sdists = [path for path in distributions if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise PublicationError(
            "assembly",
            "distribution_invalid",
            "Candidate must contain exactly one wheel and one source distribution",
            wheels=[path.name for path in wheels],
            sdists=[path.name for path in sdists],
        )
    try:
        contract = verify_release(candidate)
    except EnvironmentContractError as exc:
        raise PublicationError(
            "assembly",
            "candidate_release_invalid",
            "Candidate release contract is invalid",
            error=str(exc),
        ) from exc
    top_module = contract.descriptor.environment_factory.partition(":")[0].split(".")[0]
    source_parent: Path | None = None
    source_members: list[Path] = []
    for parent in (candidate / "src", candidate):
        package = parent / top_module
        module = parent / f"{top_module}.py"
        if package.is_dir() and not package.is_symlink():
            source_parent = parent
            source_members = [
                path
                for path in package.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            ]
            break
        if module.is_file() and not module.is_symlink():
            source_parent = parent
            source_members = [module]
            break
    if source_parent is None or not source_members:
        raise PublicationError(
            "assembly",
            "distribution_source_package_missing",
            "Environment factory top-level module has no generated source package",
            module=top_module,
        )
    try:
        with zipfile.ZipFile(wheels[0], "r") as wheel:
            files: dict[str, zipfile.ZipInfo] = {}
            for info in wheel.infolist():
                if info.is_dir():
                    continue
                relative = safe_member_path(info.filename, field="wheel member").as_posix()
                if relative in files:
                    raise PublicationError(
                        "assembly", "distribution_invalid", "Wheel contains duplicate members"
                    )
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    raise PublicationError(
                        "assembly", "distribution_invalid", "Wheel symlinks are forbidden"
                    )
                files[relative] = info
            mismatches: list[str] = []
            for source in source_members:
                relative = source.relative_to(source_parent).as_posix()
                member = files.get(relative)
                if member is None or wheel.read(member) != source.read_bytes():
                    mismatches.append(relative)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PublicationError(
            "assembly", "distribution_invalid", "Candidate wheel is unreadable", error=str(exc)
        ) from exc
    if mismatches:
        raise PublicationError(
            "assembly",
            "distribution_project_mismatch",
            "Built wheel omits or changes generated package members",
            members=mismatches,
        )


def _payload_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for top in ("project", "dist", "docs", "licenses"):
        for path in sorted(
            (root / top).rglob("*"), key=lambda item: item.relative_to(root).as_posix()
        ):
            if path.is_symlink():
                raise PublicationError(
                    "assembly", "payload_symlink_forbidden", "Symlinks are forbidden"
                )
            if not path.is_file():
                continue
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "file",
                    "mode": stat.S_IMODE(path.stat().st_mode),
                    "digest": _sha256(path.read_bytes()),
                }
            )
    return sorted(records, key=lambda item: item["path"])


def _copy_regular(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise PublicationError(
            "assembly", "candidate_member_invalid", "Candidate member is invalid"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    target.chmod(stat.S_IMODE(source.stat().st_mode))


def _bound_file(root: Path, value: Any, expected: str) -> Path:
    relative = safe_member_path(value, field=expected)
    if str(relative) != expected:
        raise PublicationError(
            "verification", "release_path_invalid", "Release path is not canonical"
        )
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise PublicationError("verification", "release_path_invalid", "Bound file is invalid")
    return path


def _bound_directory(root: Path, value: Any, expected: str) -> Path:
    relative = safe_member_path(value, field=expected)
    if str(relative) != expected:
        raise PublicationError(
            "verification", "release_path_invalid", "Release path is not canonical"
        )
    path = root / relative
    if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(root):
        raise PublicationError("verification", "release_path_invalid", "Bound directory is invalid")
    return path


def _read_json(path: Path, role: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise PublicationError("verification", "json_member_invalid", f"{role} is missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError("verification", "json_member_invalid", f"{role} is invalid") from exc


def _digest_field(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise PublicationError("verification", "digest_invalid", f"{field} is invalid")
    return value


def _require_fresh_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise PublicationError("assembly", "destination_not_fresh", "Destination must be fresh")
    path.mkdir(parents=True, exist_ok=True)


def _seal_tree(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        path.chmod(0o555)
    root.chmod(0o555)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

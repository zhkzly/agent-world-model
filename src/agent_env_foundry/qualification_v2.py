"""Pre-publication v2 Qualification Core and three-runtime materialization."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from agent_env_foundry.builder import ACTOR_FACTORY
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import (
    PreparationSettings,
    ProjectMaterializationInput,
    RuntimeLock,
    materialize_project,
)
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
)
from agent_env_foundry.qualification_contracts import (
    NativeVerificationResult,
    PublicSurfaceManifest,
    QualificationCore,
    native_verification_result_from_document,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckResult,
    atom_result_from_document,
)
from agent_env_foundry.semantics_author import SEMANTICS_FACTORY
from agent_env_foundry.semantics_inputs import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    PreparedSemanticsAuthorWorkspace,
)
from agent_env_foundry.tree_manifest import tree_manifest
from agent_env_foundry.verifier_author import (
    VERIFIER_FACTORY,
)
from agent_env_foundry.verifier_inputs import PreparedVerifierAuthorWorkspace


class QualificationV2Error(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class FrozenCoreInputs:
    expected_semantics_payload: bytes
    expected_semantics_digest: str
    public_surface: PublicSurfaceManifest
    semantics_author_inputs: PreparedSemanticsAuthorWorkspace
    verifier_author_inputs: PreparedVerifierAuthorWorkspace
    actor_project: ProjectMaterializationInput
    actor_factory: str
    semantics_project: ProjectMaterializationInput
    semantics_factory: str
    verifier_project: ProjectMaterializationInput
    verifier_factory: str


@dataclass(frozen=True, slots=True)
class QualificationRuntimeSet:
    core: QualificationCore
    actor: RuntimeLock
    semantics: RuntimeLock
    verifier: RuntimeLock


_CASE_CATEGORIES = frozenset({"positive", "noop"})


def seal_qualification_evidence(
    core: QualificationCore,
    destination: Path,
    *,
    case_records: tuple[dict[str, object], ...],
    required_capability_ids: tuple[str, ...],
) -> JSONObject:
    """Validate and persist the one C3 evidence manifest bound by a receipt."""

    if not isinstance(core, QualificationCore):
        raise QualificationV2Error("qualification_core_invalid", "evidence requires one Core")
    if not required_capability_ids or len(set(required_capability_ids)) != len(
        required_capability_ids
    ):
        raise QualificationV2Error(
            "qualification_capabilities_invalid",
            "required capability IDs must be unique and non-empty",
        )
    if any(not isinstance(item, str) or not item for item in required_capability_ids):
        raise QualificationV2Error(
            "qualification_capabilities_invalid",
            "required capability IDs must be unique non-empty strings",
        )
    normalized_cases = tuple(_validate_case_input(item) for item in case_records)
    _validate_evidence_matrix(normalized_cases, required_capability_ids)

    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise QualificationV2Error(
            "qualification_evidence_destination_exists",
            "Qualification evidence destination must be new",
        )
    try:
        (root / "cases").mkdir(parents=True)
        (root / "instances").mkdir()
        case_entries = [
            _write_case_evidence_record(root, index, record)
            for index, record in enumerate(normalized_cases, start=1)
        ]
        manifest: JSONObject = {
            "format": "qualification-evidence/3",
            "core_id": core.core_id,
            "required_capability_ids": list(required_capability_ids),
            "cases": [cast(JSONValue, item) for item in case_entries],
        }
        (root / "evidence-manifest.json").write_bytes(canonical_bytes(manifest))
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return manifest


def verify_qualification_evidence(
    core: QualificationCore,
    evidence_root: Path,
    *,
    required_capability_ids: tuple[str, ...],
) -> JSONObject:
    """Cold-read one sealed C3 evidence directory and reject any drift."""

    root = Path(evidence_root)
    if not root.is_dir() or root.is_symlink():
        raise QualificationV2Error(
            "qualification_evidence_root_invalid",
            "Qualification evidence root must be a non-symlink directory",
        )
    manifest_path = root / "evidence-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise QualificationV2Error(
            "qualification_evidence_manifest_missing",
            "Qualification evidence manifest is missing",
        )
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = _json_object(json.loads(manifest_bytes), "Qualification evidence manifest")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise QualificationV2Error(
            "qualification_evidence_manifest_invalid",
            "Qualification evidence manifest is not canonical JSON",
        ) from exc
    if manifest_bytes != canonical_bytes(manifest):
        raise QualificationV2Error(
            "qualification_evidence_manifest_invalid",
            "Qualification evidence manifest bytes are not canonical",
        )
    keys = {"format", "core_id", "required_capability_ids", "cases"}
    if set(manifest) != keys or manifest["format"] != "qualification-evidence/3":
        raise QualificationV2Error(
            "qualification_evidence_manifest_invalid",
            "Qualification evidence manifest has an invalid shape or format",
        )
    if manifest["core_id"] != core.core_id:
        raise QualificationV2Error(
            "qualification_evidence_core_mismatch",
            "Qualification evidence belongs to another Core",
        )
    if manifest["required_capability_ids"] != list(required_capability_ids):
        raise QualificationV2Error(
            "qualification_evidence_capabilities_mismatch",
            "Qualification evidence capability set differs from admission",
        )
    raw_cases = manifest["cases"]
    if not isinstance(raw_cases, list):
        raise QualificationV2Error(
            "qualification_evidence_manifest_invalid",
            "Qualification evidence entries must be arrays",
        )
    listed = {PurePosixPath("evidence-manifest.json")}
    cases: list[JSONObject] = []
    for entry in raw_cases:
        item = _json_object(entry, "case evidence entry")
        if set(item) != {"path", "digest", "category", "capability_id"}:
            raise QualificationV2Error(
                "qualification_evidence_manifest_invalid",
                "case evidence entry has unexpected fields",
            )
        record, relative = _read_evidence_record(root, item, "cases")
        if (
            record["category"] != item["category"]
            or record["capability_id"] != item["capability_id"]
        ):
            raise QualificationV2Error(
                "qualification_evidence_manifest_invalid",
                "case evidence entry metadata differs from its record",
            )
        listed.add(relative)
        sealed, instance_files = _validate_sealed_case_record(root, record)
        listed.update(instance_files)
        cases.append(sealed)
    actual = {
        PurePosixPath(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != listed:
        raise QualificationV2Error(
            "qualification_evidence_closure_mismatch",
            "Qualification evidence files differ from the manifest",
            unlisted=sorted(str(item) for item in actual - listed),
            missing=sorted(str(item) for item in listed - actual),
        )
    _validate_evidence_matrix(tuple(cases), required_capability_ids)
    return manifest


def _validate_evidence_matrix(
    cases: tuple[JSONObject, ...],
    required_capability_ids: tuple[str, ...],
) -> None:
    present_categories = {cast(str, item["category"]) for item in cases}
    missing_categories = _CASE_CATEGORIES - present_categories
    if missing_categories:
        raise QualificationV2Error(
            "qualification_evidence_categories_missing",
            "Qualification evidence omits required physical categories",
            missing=sorted(missing_categories),
        )
    positive_capabilities = {
        cast(str, item["capability_id"]) for item in cases if item["category"] == "positive"
    }
    missing_capabilities = set(required_capability_ids) - positive_capabilities
    if missing_capabilities:
        raise QualificationV2Error(
            "qualification_positive_coverage_missing",
            "Every required capability needs positive physical evidence",
            missing=sorted(missing_capabilities),
        )
    noop_capabilities = {
        cast(str, item["capability_id"]) for item in cases if item["category"] == "noop"
    }
    missing_noop = set(required_capability_ids) - noop_capabilities
    if missing_noop:
        raise QualificationV2Error(
            "qualification_noop_coverage_missing",
            "Every required capability needs a no-op physical case",
            missing=sorted(missing_noop),
        )


def _read_evidence_record(
    root: Path,
    entry: JSONObject,
    expected_directory: str,
) -> tuple[JSONObject, PurePosixPath]:
    raw_path = entry["path"]
    digest = entry["digest"]
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise QualificationV2Error(
            "qualification_evidence_manifest_invalid",
            "evidence path and digest must be strings",
        )
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not relative.parts
        or relative.parts[0] != expected_directory
    ):
        raise QualificationV2Error(
            "qualification_evidence_path_invalid",
            "evidence record path escapes its fixed directory",
            path=raw_path,
        )
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise QualificationV2Error(
            "qualification_evidence_path_invalid",
            "evidence record is missing, linked, or outside its root",
            path=raw_path,
        )
    payload = path.read_bytes()
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != digest:
        raise QualificationV2Error(
            "qualification_evidence_digest_mismatch",
            "evidence record digest differs from its manifest",
            path=raw_path,
            expected=digest,
            actual=actual_digest,
        )
    try:
        record = _json_object(json.loads(payload), f"evidence record {raw_path}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise QualificationV2Error(
            "qualification_evidence_record_invalid",
            "evidence record is not JSON",
            path=raw_path,
        ) from exc
    if payload != canonical_bytes(record):
        raise QualificationV2Error(
            "qualification_evidence_record_invalid",
            "evidence record bytes are not canonical",
            path=raw_path,
        )
    return record, relative


def _validate_case_input(value: dict[str, object]) -> JSONObject:
    keys = {
        "category",
        "capability_id",
        "start_case_id",
        "semantic_key",
        "public_descriptor",
        "before_instance_directory",
        "after_instance_directory",
        "reset_observation",
        "axis_agreement",
        "readers_unchanged",
        "trace",
        "final_answer",
        "semantics_result",
        "verifier_result",
        "answer_source_evidence",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "physical case record has unexpected fields",
        )
    normalized = _json_object(value, "physical case record")
    before = normalized["before_instance_directory"]
    after = normalized["after_instance_directory"]
    if (
        not isinstance(before, str)
        or not isinstance(after, str)
        or Path(before).resolve() == Path(after).resolve()
    ):
        raise QualificationV2Error(
            "qualification_case_instances_invalid",
            "physical case before/after directories must be distinct paths",
        )
    for field in ("start_case_id", "semantic_key"):
        item = normalized[field]
        if not isinstance(item, str) or not item or any(character.isspace() for character in item):
            raise QualificationV2Error(
                "qualification_case_record_invalid",
                f"physical case {field} is invalid",
            )
    if not is_json_object(normalized["public_descriptor"]):
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "physical case public_descriptor must be an object",
        )
    _validate_case_semantics(normalized)
    return normalized


def _validate_sealed_case_record(
    root: Path,
    value: JSONObject,
) -> tuple[JSONObject, set[PurePosixPath]]:
    keys = {
        "category",
        "capability_id",
        "start_case_id",
        "semantic_key",
        "public_descriptor",
        "before_instance_path",
        "after_instance_path",
        "before_tree_digest",
        "after_tree_digest",
        "reset_observation",
        "axis_agreement",
        "readers_unchanged",
        "trace",
        "final_answer",
        "semantics_result",
        "verifier_result",
        "answer_source_evidence",
    }
    if set(value) != keys:
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "sealed physical case record has unexpected fields",
        )
    files: set[PurePosixPath] = set()
    for prefix in ("before", "after"):
        path_field = f"{prefix}_instance_path"
        digest_field = f"{prefix}_tree_digest"
        raw_path = value[path_field]
        digest = value[digest_field]
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise QualificationV2Error(
                "qualification_case_record_invalid",
                "sealed physical case instance path or digest is invalid",
            )
        relative = PurePosixPath(raw_path)
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or not relative.parts
            or relative.parts[0] != "instances"
        ):
            raise QualificationV2Error(
                "qualification_evidence_path_invalid",
                "sealed physical instance path escapes evidence root",
            )
        instance = root / relative
        if instance.is_symlink() or not instance.is_dir():
            raise QualificationV2Error(
                "qualification_case_instances_invalid",
                "sealed physical instance directory is missing or linked",
            )
        if tree_manifest(instance).digest != digest:
            raise QualificationV2Error(
                "qualification_case_tree_mismatch",
                "sealed physical instance tree differs from its case record",
                path=raw_path,
            )
        files.update(
            PurePosixPath(path.relative_to(root).as_posix())
            for path in instance.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    _validate_case_semantics(value)
    return value, files


def _validate_case_semantics(normalized: JSONObject) -> None:
    category = normalized["category"]
    capability_id = normalized["capability_id"]
    if category not in _CASE_CATEGORIES or not isinstance(capability_id, str) or not capability_id:
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "physical case category or capability ID is invalid",
        )
    if normalized["axis_agreement"] is not True:
        raise QualificationV2Error(
            "qualification_reader_disagreement",
            "physical case was not admitted by both readers",
            category=category,
            capability_id=capability_id,
        )
    if normalized["readers_unchanged"] is not True:
        raise QualificationV2Error(
            "qualification_reader_mutation",
            "a Qualification reader changed its project or instance tree",
            category=category,
            capability_id=capability_id,
        )
    if not isinstance(normalized["trace"], list) or not is_json_value(normalized["final_answer"]):
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "physical case trace or final answer is invalid",
        )
    if not is_json_value(normalized["reset_observation"]) or not isinstance(
        normalized["answer_source_evidence"], list
    ):
        raise QualificationV2Error(
            "qualification_case_record_invalid",
            "physical case reset observation or answer-source evidence is invalid",
        )
    try:
        semantic = atom_result_from_document(normalized["semantics_result"])
        verifier = native_verification_result_from_document(normalized["verifier_result"])
    except Exception as exc:
        raise QualificationV2Error(
            "qualification_case_result_invalid",
            str(exc),
        ) from exc
    if not _results_agree(semantic, verifier):
        raise QualificationV2Error(
            "qualification_reader_disagreement",
            "TaskSemantics and native audit disagree on required effects or collateral",
            category=category,
            capability_id=capability_id,
        )
    validate_qualification_case_outcome(
        category,
        semantic,
        verifier,
        capability_id=capability_id,
    )


def validate_qualification_case_outcome(
    category: str,
    semantic: AtomCheckResult,
    verifier: NativeVerificationResult,
    *,
    capability_id: str | None = None,
) -> None:
    if category == "positive":
        valid = semantic.satisfied and verifier.satisfied
    elif category == "noop":
        valid = (
            not semantic.initially_satisfied
            and not semantic.satisfied
            and semantic.collateral_ok
            and semantic.process_ok is not True
            and verifier.collateral_ok
        )
    else:
        valid = False
    if not valid:
        expected: JSONObject = (
            {"semantics_satisfied": True, "verifier_satisfied": True}
            if category == "positive"
            else {
                "semantics_initially_satisfied": False,
                "semantics_satisfied": False,
                "semantics_collateral_ok": True,
                "semantics_process_ok": False,
                "verifier_collateral_ok": True,
            }
        )
        raise QualificationV2Error(
            "qualification_case_outcome_invalid",
            "physical case did not discriminate its declared category",
            category=category,
            capability_id=capability_id,
            expected=expected,
            semantics_result=semantic.to_document(),
            verifier_result=verifier.to_document(),
        )


def _results_agree(
    semantic: AtomCheckResult,
    verifier: NativeVerificationResult,
) -> bool:
    return (
        semantic.required_effects_ok == verifier.required_effects_ok
        and semantic.collateral_ok == verifier.collateral_ok
    )


def _write_case_evidence_record(
    root: Path,
    index: int,
    record: JSONObject,
) -> JSONObject:
    before_source = Path(cast(str, record["before_instance_directory"]))
    after_source = Path(cast(str, record["after_instance_directory"]))
    instance_root = root / f"instances/{index:03d}"
    before_relative = f"instances/{index:03d}/before"
    after_relative = f"instances/{index:03d}/after"
    before_digest = _copy_evidence_tree(before_source, instance_root / "before")
    after_digest = _copy_evidence_tree(after_source, instance_root / "after")
    persisted: JSONObject = {
        key: value
        for key, value in record.items()
        if key not in {"before_instance_directory", "after_instance_directory"}
    }
    persisted.update(
        {
            "before_instance_path": before_relative,
            "after_instance_path": after_relative,
            "before_tree_digest": before_digest,
            "after_tree_digest": after_digest,
        }
    )
    return _write_evidence_record(root, "cases", index, persisted)


def _copy_evidence_tree(source: Path, destination: Path) -> str:
    manifest = tree_manifest(source)
    if any(item.object_type not in {"file", "directory"} for item in manifest.records):
        raise QualificationV2Error(
            "qualification_case_tree_invalid",
            "physical evidence tree contains a symlink or non-file object",
            path=str(source),
        )
    shutil.copytree(source, destination)
    copied = tree_manifest(destination)
    if copied.digest != manifest.digest:
        raise QualificationV2Error(
            "qualification_case_tree_copy_mismatch",
            "archived physical evidence differs from its source tree",
            path=str(source),
        )
    return copied.digest


def _write_evidence_record(
    root: Path,
    directory: str,
    index: int,
    record: JSONObject,
) -> JSONObject:
    payload = canonical_bytes(record)
    digest = hashlib.sha256(payload).hexdigest()
    relative = f"{directory}/{index:03d}-{digest}.json"
    (root / relative).write_bytes(payload)
    entry: JSONObject = {
        "path": relative,
        "digest": digest,
    }
    if directory == "cases":
        entry["category"] = record["category"]
        entry["capability_id"] = record["capability_id"]
    else:
        entry["mutant_id"] = record["mutant_id"]
        entry["target_role"] = record["target_role"]
    return entry


def _json_object(value: object, role: str) -> JSONObject:
    if not is_json_value(value):
        raise QualificationV2Error(
            "qualification_evidence_not_json",
            f"{role} is not JSON",
        )
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    if not is_json_object(normalized):
        raise QualificationV2Error(
            "qualification_evidence_not_json",
            f"{role} must be a JSON object",
        )
    return cast(JSONObject, normalized)


def derive_qualification_core(inputs: FrozenCoreInputs) -> QualificationCore:
    _validate_frozen_inputs(inputs)
    for project in (
        inputs.actor_project,
        inputs.semantics_project,
        inputs.verifier_project,
    ):
        try:
            actual = compute_authored_project_digest(
                project.source_root,
                project.role,
                require_locked_project=True,
            )
        except ProjectIdentityError as exc:
            raise QualificationV2Error(
                "core_project_invalid",
                str(exc),
                role=project.role,
                path=exc.path,
            ) from exc
        if actual != project.project_digest:
            raise QualificationV2Error(
                "core_project_digest_mismatch",
                "project differs before Qualification Core derivation",
                role=project.role,
                expected=project.project_digest,
                actual=actual,
            )
    return _core_from_declarations(inputs)


def materialize_qualification_core(
    inputs: FrozenCoreInputs,
    core: QualificationCore,
    cache_root: Path,
    *,
    settings: PreparationSettings,
) -> QualificationRuntimeSet:
    _validate_frozen_inputs(inputs)
    declared = _core_from_declarations(inputs)
    if declared != core:
        raise QualificationV2Error(
            "qualification_core_mismatch",
            "materialization inputs differ from the supplied Qualification Core",
            expected=core.to_document(),
            actual=declared.to_document(),
        )
    requested_cache = Path(cache_root)
    if requested_cache.is_symlink():
        raise QualificationV2Error(
            "qualification_cache_symlink",
            "Qualification cache root must not be a symlink",
        )
    cache = requested_cache.resolve()
    source_roots = tuple(
        project.source_root.resolve()
        for project in (
            inputs.actor_project,
            inputs.semantics_project,
            inputs.verifier_project,
        )
    )
    if any(
        cache == source or cache.is_relative_to(source) or source.is_relative_to(cache)
        for source in source_roots
    ):
        raise QualificationV2Error(
            "qualification_cache_overlaps_source",
            "Qualification cache and frozen project roots must be disjoint",
        )
    runtime_root = cache / "qualification-cores" / core.core_id
    actor = materialize_project(
        inputs.actor_project,
        runtime_root / "actor",
        settings=settings,
    )
    semantics = materialize_project(
        inputs.semantics_project,
        runtime_root / "semantics",
        settings=settings,
    )
    verifier = materialize_project(
        inputs.verifier_project,
        runtime_root / "verifier",
        settings=settings,
    )
    return QualificationRuntimeSet(core, actor, semantics, verifier)


def _validate_frozen_inputs(inputs: FrozenCoreInputs) -> None:
    if not isinstance(inputs, FrozenCoreInputs):
        raise QualificationV2Error("core_inputs_invalid", "Core inputs use the wrong type")
    actual_expected = hashlib.sha256(inputs.expected_semantics_payload).hexdigest()
    if actual_expected != inputs.expected_semantics_digest:
        raise QualificationV2Error(
            "expected_semantics_digest_mismatch",
            "Expected Semantics bytes differ from their frozen digest",
        )
    if not isinstance(inputs.public_surface, PublicSurfaceManifest):
        raise QualificationV2Error(
            "public_surface_invalid",
            "Qualification Core requires one public-surface/2 manifest",
        )
    projects = (
        (inputs.actor_project, "actor", inputs.actor_factory, ACTOR_FACTORY),
        (
            inputs.semantics_project,
            "semantics",
            inputs.semantics_factory,
            SEMANTICS_FACTORY,
        ),
        (
            inputs.verifier_project,
            "verifier",
            inputs.verifier_factory,
            VERIFIER_FACTORY,
        ),
    )
    roots: list[Path] = []
    for project, role, factory, fixed_factory in projects:
        if project.role != role or factory != fixed_factory:
            raise QualificationV2Error(
                "core_project_role_invalid",
                "Core project role/factory differs from the fixed contract",
                role=role,
            )
        module = factory.partition(":")[0].partition(".")[0]
        if project.own_module != module:
            raise QualificationV2Error(
                "core_project_module_invalid",
                "Core project module differs from its factory",
                role=role,
            )
        if project.source_root.is_symlink():
            raise QualificationV2Error(
                "core_project_root_symlink",
                "Core project root must not be a symlink",
                role=role,
            )
        roots.append(project.source_root.resolve())
    if len(set(roots)) != 3:
        raise QualificationV2Error(
            "core_project_roots_aliased",
            "Actor, semantics and verifier project roots must be distinct",
        )
    if any(
        left.is_relative_to(right) or right.is_relative_to(left)
        for index, left in enumerate(roots)
        for right in roots[index + 1 :]
    ):
        raise QualificationV2Error(
            "core_project_roots_nested",
            "Actor, semantics and verifier project roots must not contain one another",
        )
    actor_module = inputs.actor_project.own_module
    semantics_module = inputs.semantics_project.own_module
    expected_forbidden = {
        "actor": (semantics_module, "generated_qualification_verifier", "agent_env_foundry"),
        "semantics": (actor_module, "generated_qualification_verifier", "agent_env_foundry"),
        "verifier": (actor_module, semantics_module, "agent_env_foundry"),
    }
    for project in (
        inputs.actor_project,
        inputs.semantics_project,
        inputs.verifier_project,
    ):
        if project.forbidden_modules != expected_forbidden[project.role]:
            raise QualificationV2Error(
                "core_forbidden_modules_invalid",
                "Core project forbidden_modules differ from the fixed visibility matrix",
                role=project.role,
                expected=list(expected_forbidden[project.role]),
                actual=list(project.forbidden_modules),
            )
    _validate_author_handoffs(inputs)


def _core_from_declarations(inputs: FrozenCoreInputs) -> QualificationCore:
    return QualificationCore(
        expected_semantics_digest=inputs.expected_semantics_digest,
        actor_project_digest=inputs.actor_project.project_digest,
        actor_factory=inputs.actor_factory,
        semantics_project_digest=inputs.semantics_project.project_digest,
        semantics_factory=inputs.semantics_factory,
        verifier_project_digest=inputs.verifier_project.project_digest,
        verifier_factory=inputs.verifier_factory,
        public_surface_manifest_digest=inputs.public_surface.manifest_digest,
    )


def _validate_author_handoffs(inputs: FrozenCoreInputs) -> None:
    semantics_inputs = inputs.semantics_author_inputs
    verifier_inputs = inputs.verifier_author_inputs
    if not isinstance(semantics_inputs, PreparedSemanticsAuthorWorkspace) or not isinstance(
        verifier_inputs, PreparedVerifierAuthorWorkspace
    ):
        raise QualificationV2Error(
            "author_input_attestation_invalid",
            "Core requires typed Semantics and Verifier author input attestations",
        )
    if (
        semantics_inputs.root.resolve() != inputs.semantics_project.source_root.resolve()
        or verifier_inputs.root.resolve() != inputs.verifier_project.source_root.resolve()
    ):
        raise QualificationV2Error(
            "author_project_root_mismatch",
            "Author input attestation root differs from generated project root",
        )
    try:
        semantics_inputs.verify_inputs()
        verifier_inputs.verify_inputs()
    except ValueError as exc:
        raise QualificationV2Error(
            "author_inputs_changed",
            "Author immutable inputs or actor view changed before Core derivation",
        ) from exc
    expected_payload = inputs.expected_semantics_payload
    for prepared in (semantics_inputs, verifier_inputs):
        if (prepared.root / EXPECTED_TASK_SEMANTICS_NAME).read_bytes() != expected_payload:
            raise QualificationV2Error(
                "author_expected_semantics_mismatch",
                "Core Expected Semantics differs from Author input bytes",
            )
    surface_payload = canonical_bytes(inputs.public_surface.to_document())
    for prepared in (semantics_inputs, verifier_inputs):
        if (prepared.root / PUBLIC_SURFACE_NAME).read_bytes() != surface_payload:
            raise QualificationV2Error(
                "author_public_surface_mismatch",
                "Core Public Surface differs from Author input bytes",
            )
    actor_digest = inputs.actor_project.project_digest
    if (
        semantics_inputs.view_manifest.candidate_digest != actor_digest
        or verifier_inputs.view_manifest.actor_digest != actor_digest
    ):
        raise QualificationV2Error(
            "author_actor_digest_mismatch",
            "Author actor views differ from the Core actor project",
        )
    semantics_view = tuple(
        (item.path, item.digest) for item in semantics_inputs.view_manifest.files
    )
    verifier_view = tuple((item.path, item.digest) for item in verifier_inputs.view_manifest.files)
    if semantics_view != verifier_view:
        raise QualificationV2Error(
            "author_actor_views_mismatch",
            "Semantics and Verifier Authors received different actor bytes",
        )


__all__ = [
    "FrozenCoreInputs",
    "QualificationRuntimeSet",
    "QualificationV2Error",
    "derive_qualification_core",
    "materialize_qualification_core",
    "seal_qualification_evidence",
    "validate_qualification_case_outcome",
    "verify_qualification_evidence",
]

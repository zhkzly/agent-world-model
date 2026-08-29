"""Pre-publication v2 Qualification Core and three-runtime materialization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_env_foundry.builder import ACTOR_FACTORY
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
    PublicSurfaceManifest,
    QualificationCore,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics_author import SEMANTICS_FACTORY
from agent_env_foundry.semantics_inputs import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    PreparedSemanticsAuthorWorkspace,
)
from agent_env_foundry.verifier_author import VERIFIER_FACTORY
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
]

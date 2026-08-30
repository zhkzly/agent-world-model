from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent_env_foundry.qualification_contracts import (
    NativeVerificationRequest,
    NativeVerificationResult,
    PublicSurfaceManifest,
    QualificationContractError,
    QualificationCore,
    QualificationReceipt,
    QualifiedCatalogManifest,
    QualifiedStartCasesManifest,
    RequirementCoverageEntry,
    RequirementCoverageManifest,
    native_verification_request_from_document,
    native_verification_result_from_document,
    public_surface_manifest_from_document,
    qualification_core_from_document,
    qualification_receipt_from_document,
    qualified_catalog_manifest_from_document,
    qualified_start_cases_manifest_from_document,
    requirement_coverage_manifest_from_document,
)
from agent_env_foundry.semantics import CapabilitySpec, RenderingSpec, StartCase, TraceEvent

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64
DIGEST_1 = "1" * 64
DIGEST_2 = "2" * 64
DIGEST_3 = "3" * 64
DIGEST_4 = "4" * 64


def _surface() -> PublicSurfaceManifest:
    return PublicSurfaceManifest(
        start_schema={
            "type": "object",
            "properties": {"seed": {"type": "integer"}},
            "required": ["seed"],
            "additionalProperties": False,
        },
        reset_observation_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        tool_specs=(
            {
                "name": "increment",
                "description": "Increment a counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {"amount": {"type": "integer"}},
                    "required": ["amount"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            },
        ),
        public_documents_digest=DIGEST_A,
    )


def _core() -> QualificationCore:
    return QualificationCore(
        expected_semantics_digest=DIGEST_A,
        actor_project_digest=DIGEST_B,
        actor_factory="generated_actor.release:make_environment",
        semantics_project_digest=DIGEST_C,
        semantics_factory="generated_task_semantics.release:make_semantics",
        verifier_project_digest=DIGEST_D,
        verifier_factory="generated_qualification_verifier.release:make_verifier",
        public_surface_manifest_digest=_surface().manifest_digest,
    )


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="increment",
        requirement_ids=("REQ-1",),
        workflow_ids=("counter",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="increment the counter",
        protected_binding_schema={"type": "object", "additionalProperties": True},
        public_descriptor_schema={"type": "object", "additionalProperties": True},
        facets=(),
        conditions=(),
        answer_fields=(),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("increment", "counter", None),
    )


def test_core_identity_is_acyclic_and_binds_every_frozen_code_lineage() -> None:
    core = _core()
    document = core.to_document()
    assert "release_id" not in document
    assert "qualification" not in document
    assert document["verifier_project_digest"] == DIGEST_D
    assert core.core_id != replace(core, verifier_project_digest=DIGEST_E).core_id
    assert qualification_core_from_document(core.to_document()) == core
    extra = core.to_document()
    extra["release_id"] = DIGEST_F
    with pytest.raises(QualificationContractError, match="exactly"):
        qualification_core_from_document(extra)
    with pytest.raises(QualificationContractError, match="fixed"):
        replace(core, verifier_factory="custom.verifier:make")


def test_strict_receipt_rejects_mechanical_or_unknown_documents() -> None:
    core = _core()
    receipt = QualificationReceipt(
        core_id=core.core_id,
        expected_semantics_digest=core.expected_semantics_digest,
        actor_project_digest=core.actor_project_digest,
        semantics_project_digest=core.semantics_project_digest,
        verifier_project_digest=core.verifier_project_digest,
        public_surface_manifest_digest=core.public_surface_manifest_digest,
        qualified_catalog_digest=DIGEST_E,
        requirement_coverage_digest=DIGEST_F,
        qualified_start_cases_digest=DIGEST_1,
        evidence_manifest_digest=DIGEST_2,
    )
    parsed = qualification_receipt_from_document(receipt.to_document())
    assert parsed == receipt
    receipt.validate_core(core)
    assert "release_id" not in receipt.to_document()
    with pytest.raises(QualificationContractError, match="exactly"):
        qualification_receipt_from_document(
            {"format": "environment-qualification/2", "verdict": "mechanical_fixture_only"}
        )
    bad = receipt.to_document()
    bad["verdict"] = "failed"
    with pytest.raises(QualificationContractError, match="passed"):
        qualification_receipt_from_document(bad)
    with pytest.raises(QualificationContractError, match="Core"):
        receipt.validate_core(replace(core, actor_project_digest=DIGEST_3))


def test_sealed_surface_coverage_and_start_cases_have_canonical_identities() -> None:
    surface = _surface()
    assert surface.tool_catalog_digest
    coverage = RequirementCoverageManifest(
        (
            RequirementCoverageEntry("REQ-1", "Taskable", ("increment",), ("case-1",)),
            RequirementCoverageEntry("REQ-2", "Unsupported", (), ("evidence-2",)),
        )
    )
    starts = QualifiedStartCasesManifest(
        seed=0,
        requested_limit=2,
        cases=(StartCase("case-1", {"seed": 0}, ("baseline",)),),
    )
    starts.validate_against(surface)
    catalog = QualifiedCatalogManifest((_capability(),))
    assert catalog.catalog_digest
    assert coverage.coverage_digest
    assert starts.start_cases_digest
    assert public_surface_manifest_from_document(surface.to_document()) == surface
    bad_surface = surface.to_document()
    bad_surface["tool_catalog_digest"] = DIGEST_4
    with pytest.raises(QualificationContractError, match="tool catalog digest"):
        public_surface_manifest_from_document(bad_surface)
    assert qualified_catalog_manifest_from_document(catalog.to_document()) == catalog
    assert requirement_coverage_manifest_from_document(coverage.to_document()) == coverage
    assert qualified_start_cases_manifest_from_document(starts.to_document()) == starts
    with pytest.raises(QualificationContractError, match="Taskable"):
        RequirementCoverageEntry("REQ-3", "Taskable", (), ("case-3",))
    invalid_starts = QualifiedStartCasesManifest(
        seed=0,
        requested_limit=1,
        cases=(StartCase("bad", {"seed": "not-an-integer"}, ("bad",)),),
    )
    with pytest.raises(QualificationContractError, match="integer"):
        invalid_starts.validate_against(surface)


def test_native_verifier_request_has_no_tasksemantics_protected_projection() -> None:
    request = NativeVerificationRequest(
        capability_id="increment",
        start_case_id="case-1",
        public_descriptor={"name": "counter"},
        public_trace=(
            TraceEvent(
                1,
                "increment",
                {"amount": 1},
                {"ok": True, "data": {"count": 1}, "error": None},
            ),
        ),
        before_instance_directory=Path("/instances/before"),
        after_instance_directory=Path("/instances/after"),
    )
    document = request.to_document()
    assert "protected_binding" not in document
    assert "before_facts" not in document
    assert "after_facts" not in document
    assert native_verification_request_from_document(document) == request
    with pytest.raises(QualificationContractError, match="distinct"):
        replace(request, after_instance_directory=request.before_instance_directory)

    result = NativeVerificationResult(True, True, ())
    assert result.satisfied
    assert native_verification_result_from_document(result.to_document()) == result
    with pytest.raises(QualificationContractError, match="boolean"):
        native_verification_result_from_document(
            {
                **result.to_document(),
                "required_effects_ok": "yes",
            }
        )

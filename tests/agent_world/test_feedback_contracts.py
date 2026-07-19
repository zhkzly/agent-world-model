from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.control.feedback import (
    PRODUCTION_FEEDBACK,
    FeedbackResult,
    RepairTargetRef,
)
from agent_world.controller import FoundryController
from agent_world.designer.service import EnvironmentDesigner


def test_every_feedback_contract_has_coherent_repair_policy() -> None:
    assert len(PRODUCTION_FEEDBACK.contracts) == 14
    for contract in PRODUCTION_FEEDBACK.contracts:
        if contract.repair_owner_component is None:
            assert contract.repair_slot is None
            assert contract.maximum_attempts == 0
            assert contract.maximum_automatic_backjump == 0
        else:
            assert contract.repair_slot is not None
            assert contract.maximum_attempts > 0


@pytest.mark.parametrize(
    ("contract_id", "claim_id", "effect"),
    (
        ("feedback.design.modeling_gate", "design.valid", "block_integration"),
        ("feedback.build.candidate", "build.valid", "block_integration"),
        ("feedback.verifier.intent", "verifier.valid", "block_release"),
        ("feedback.integration.runtime", "integration.ready", "block_release"),
        ("feedback.judge.release", "release_judge.valid", "block_release"),
        (
            "feedback.controller.observability",
            "observability.release_ready",
            "block_release",
        ),
    ),
)
def test_release_claim_policy_is_compiled_from_feedback_catalog(
    contract_id: str,
    claim_id: str,
    effect: str,
) -> None:
    assert FoundryController._release_feedback_claim_policy(contract_id) == (
        claim_id,
        effect,
    )


def test_repairable_feedback_binds_exact_target_and_claim(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="feedback-contract-test",
        allowed_artifact_type_prefixes=("design.", "control."),
    )
    subject_ref = writer.put_json(
        artifact_id="design:architecture",
        artifact_type="design.world_architecture_source",
        value={"architecture": "hotel"},
    )
    evidence_ref = writer.put_json(
        artifact_id="validation:architecture",
        artifact_type="control.validation_diagnostic",
        value={"status": "passed"},
        dependencies=(subject_ref,),
    )
    target = RepairTargetRef(
        target_id="repair-target:architecture",
        component="design",
        artifact_slot="world_architecture",
        lineage_id="job:hotel.world-architecture",
        immutable_input_refs=(subject_ref,),
        committed_subject_ref=subject_ref,
        allowed_mutation_paths=("/",),
    )
    result = FeedbackResult(
        result_id="feedback-result:architecture",
        contract_id="feedback.design.world_architecture",
        claim_id="design.architecture.compiles",
        target=target,
        status="passed",
        subject_ref=subject_ref,
        evidence_refs=(evidence_ref,),
        evaluated_at=datetime.now(UTC),
        summary="The exact architecture revision compiled.",
    )

    assert PRODUCTION_FEEDBACK.validate_result(result).maximum_attempts == 2
    with pytest.raises(ValueError, match="claim"):
        PRODUCTION_FEEDBACK.validate_result(
            result.model_copy(update={"claim_id": "design.wrong-claim"})
        )
    with pytest.raises(ValueError, match="committed repair target"):
        PRODUCTION_FEEDBACK.validate_result(
            result.model_copy(
                update={
                    "target": target.model_copy(update={"committed_subject_ref": None})
                }
            )
        )


def test_shared_tool_policy_uses_its_own_production_repair_boundary() -> None:
    target = EnvironmentDesigner._shared_tool_semantics_repair_target(
        job_id="job:hotel",
        group_id="tool-group:hotel",
        immutable_input_refs=(),
    )

    contract = PRODUCTION_FEEDBACK.require_for_target(
        "feedback.design.shared_tool_semantics",
        target,
    )

    assert contract.claim_id == "design.shared_tool_semantics.compiles"
    assert contract.repair_slot == "shared_tool_semantics"
    assert target.allowed_mutation_paths == (
        "/atomicity_domains",
        "/concurrency_domains",
        "/idempotency_domains",
        "/ordering_constraints",
        "/compensation_edges",
        "/error_policies",
    )
    with pytest.raises(ValueError, match="slot"):
        PRODUCTION_FEEDBACK.require_for_target(
            "feedback.design.tool_semantics",
            target,
        )


def test_observation_only_feedback_never_invents_repair_target(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="feedback-observability-test",
        allowed_artifact_type_prefixes=("control.",),
    )
    subject_ref = writer.put_json(
        artifact_id="telemetry:summary",
        artifact_type="control.telemetry_summary",
        value={"complete": True},
    )
    evidence_ref = writer.put_json(
        artifact_id="telemetry:evidence",
        artifact_type="control.telemetry_evidence",
        value={"spans": 5},
        dependencies=(subject_ref,),
    )
    result = FeedbackResult(
        result_id="feedback-result:telemetry",
        contract_id="feedback.controller.observability",
        claim_id="observability.release_ready",
        status="passed",
        subject_ref=subject_ref,
        evidence_refs=(evidence_ref,),
        evaluated_at=datetime.now(UTC),
        summary="Release telemetry covers every required operation.",
    )

    contract = PRODUCTION_FEEDBACK.validate_result(result)
    assert contract.repair_owner_component is None
    assert result.target is None


def test_terminal_semantic_failure_records_one_committed_diagnostic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="feedback-terminal-test",
        allowed_artifact_type_prefixes=("design.", "control."),
    )
    input_ref = writer.put_json(
        artifact_id="design:evidence-input",
        artifact_type="design.evidence_graph",
        value={"graph": "hotel"},
    )
    target = RepairTargetRef(
        target_id="repair-target:world-architecture",
        component="design",
        artifact_slot="world_architecture",
        lineage_id="job:hotel.world-architecture",
        immutable_input_refs=(input_ref,),
        allowed_mutation_paths=("/",),
    )
    designer = EnvironmentDesigner.__new__(EnvironmentDesigner)
    designer.artifacts = writer

    result_ref = designer._record_feedback_terminal(
        contract_id="feedback.design.world_architecture",
        target=target,
        status="failed",
        issue_codes=("schema_reference_missing",),
        summary="The architecture remained invalid after bounded correction.",
        results=(),
    )

    assert result_ref is not None
    result = store.get_json(result_ref, FeedbackResult)
    assert result.status == "failed"
    assert result.diagnostic_ref is not None
    assert result.target is not None
    assert result.target.committed_subject_ref is None
    assert result.target.attempt_commitment is not None
    assert result.usage.agent_turns == 0
    assert result.usage_unknown_dimensions == ()

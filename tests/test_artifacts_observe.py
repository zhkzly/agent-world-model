from __future__ import annotations

from pathlib import Path

import pytest
from test_direct_release import _release_candidate as _base_release_candidate

from agent_world.artifacts import (
    ArtifactIntegrityError,
    ArtifactSafetyError,
    ArtifactStore,
)
from agent_world.candidate import _cold_read_package
from agent_world.contracts import ArtifactRef, DirectRun, EnvironmentRequest
from agent_world.graph import design_graph
from agent_world.observe import ObserveError, observe_run


def _release_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str = "run_release",
):
    return _base_release_candidate(tmp_path, monkeypatch, run_id=run_id)


def test_artifacts_are_immutable_and_rechecked_on_read(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "run")
    ref = store.put_json("design.contract", {"name": "demo"})

    assert store.put_json("design.contract", {"name": "demo"}) == ref
    assert store.read_json(ref) == {"name": "demo"}

    (tmp_path / "run" / ref.path).write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError, match="artifact_digest_mismatch"):
        store.read_json(ref)


def test_artifact_store_rejects_private_or_raw_provider_fields(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "run")

    with pytest.raises(ArtifactSafetyError, match="artifact_forbidden_field"):
        store.put_json("research.evidence", {"raw_provider_payload": {"choices": []}})
    with pytest.raises(ArtifactSafetyError, match="candidate_control_claim"):
        store.put_json("candidate.completion", {"release": "released"})


def test_run_facts_are_atomic_enveloped_and_hash_checked(tmp_path: Path) -> None:
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    store = ArtifactStore(tmp_path / "runs" / run.run_id)
    store.write_run(run)

    assert store.read_run()["run_id"] == run.run_id
    run_path = tmp_path / "runs" / run.run_id / "run.json"
    run_path.write_bytes(run_path.read_bytes().replace(b"running", b"rejected", 1))
    with pytest.raises(ArtifactIntegrityError, match="run_digest_mismatch"):
        store.read_run()


def test_observe_never_creates_missing_state(tmp_path: Path) -> None:
    state_root = tmp_path / "state"

    with pytest.raises(ObserveError, match="observe_scope_not_found"):
        observe_run(state_root, "run_missing")

    assert not state_root.exists()


def test_observe_requires_registry_receipt_and_package_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    _, store, _, result = _release_candidate(tmp_path, monkeypatch, run_id=run.run_id)
    run.finish("released", package_ref=result.package_ref)
    store.write_run(run)

    scene = observe_run(state_root, run.run_id)
    assert scene["release"]["status"] == "released"
    assert scene["release"]["package_id"] == "direct-support-records"

    package_path = (
        state_root / "registry" / "packages" / f"{result.package_ref.package_digest[7:]}.zip"
    )
    package_path.write_bytes(b"tampered package")

    assert observe_run(state_root, run.run_id)["release"] == {"status": "not_published"}


@pytest.mark.parametrize(
    "case",
    [
        "binding_missing",
        "binding_altered",
        "binding_extra_field",
        "gate_evidence_extra_field",
    ],
)
def test_observe_rejects_altered_judge_gate_evidence_after_cold_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    state_root = tmp_path / "state"
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    _, store, _, result = _release_candidate(tmp_path, monkeypatch, run_id=run.run_id)
    run.finish("released", package_ref=result.package_ref)
    store.write_run(run)

    assert observe_run(state_root, run.run_id)["release"]["status"] == "released"

    original_read_json = ArtifactStore.read_json
    judge = store.read_envelope(result.package_ref.judge_report_ref)["payload"]
    first_gate_id = judge["gates"][0]["gate_id"]

    def altered_read_json(instance: ArtifactStore, ref: ArtifactRef):
        payload = original_read_json(instance, ref)
        if ref.kind != "judge.gate_evidence":
            return payload
        evidence = dict(payload)
        if case == "binding_missing" and evidence["gate_id"] == first_gate_id:
            evidence.pop("binding")
        elif case == "binding_altered" and evidence["gate_id"] == first_gate_id:
            evidence["binding"] = {**evidence["binding"], "tool_index": 99}
        elif case == "binding_extra_field" and evidence["gate_id"] == first_gate_id:
            evidence["binding"] = {**evidence["binding"], "extra": "unexpected"}
        elif case == "gate_evidence_extra_field" and evidence["gate_id"] == first_gate_id:
            evidence["extra"] = "unexpected"
        return evidence

    monkeypatch.setattr(ArtifactStore, "read_json", altered_read_json)

    assert observe_run(state_root, run.run_id)["release"] == {"status": "not_published"}


def test_observe_discovers_failed_work_and_safe_finding_without_run_refs(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    store = ArtifactStore(state_root / "runs" / run.run_id)
    subject = store.put_json("design.input", {"name": "demo"})
    evidence = store.put_json("control.evidence", {"code": "demo_failure"})
    design_graph().fail(
        store,
        run.run_id,
        "world_architecture",
        (subject,),
        "demo_failure",
        subject_ref=subject,
        evidence_refs=(evidence,),
        category="node_execution",
        expected_condition="a safe design contract",
    )
    run.finish("rejected", code="demo_failure")
    store.write_run(run)

    scene = observe_run(state_root, run.run_id)

    assert [work["node"] for work in scene["works"]] == ["world_architecture"]
    finding = scene["findings"]
    assert len(finding) == 1
    assert finding[0] == {
        "finding_id": finding[0]["finding_id"],
        "owner": "designer",
        "code": "demo_failure",
        "category": "node_execution",
        "severity": "block_release",
        "expected_condition": "a safe design contract",
        "blocks_release": True,
        "subject_id": subject.artifact_id,
        "evidence_ids": [evidence.artifact_id],
    }
    assert scene["terminal_code"] == "demo_failure"


def test_observe_downgrades_when_verifier_or_lineage_closure_is_tampered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    _, store, _, result = _release_candidate(tmp_path, monkeypatch, run_id=run.run_id)
    package_ref = result.package_ref
    run.finish("released", package_ref=package_ref)
    store.write_run(run)

    assert observe_run(state_root, run.run_id)["release"]["status"] == "released"
    package = _cold_read_package(
        (
            state_root / "registry" / "packages" / f"{package_ref.package_digest[7:]}.zip"
        ).read_bytes(),
        package_ref.package_digest,
    )
    verifier_ref = ArtifactRef(**package["manifest"]["artifact_refs"]["verifier"])
    (store.run_root / verifier_ref.path).write_bytes(b"{}")

    assert observe_run(state_root, run.run_id)["release"] == {"status": "not_published"}

    lineage_parent = tmp_path / "lineage"
    lineage_root = lineage_parent / "state"
    lineage_run = DirectRun.create(request)
    _, lineage_store, _, lineage_result = _release_candidate(
        lineage_parent, monkeypatch, run_id=lineage_run.run_id
    )
    lineage_ref = lineage_result.package_ref
    lineage_run.finish("released", package_ref=lineage_ref)
    lineage_store.write_run(lineage_run)
    (lineage_store.run_root / lineage_ref.semantic_lineage_ref.path).write_bytes(b"{}")

    assert observe_run(lineage_root, lineage_run.run_id)["release"] == {"status": "not_published"}

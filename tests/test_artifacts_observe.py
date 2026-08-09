from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from agent_world.artifacts import (
    ArtifactIntegrityError,
    ArtifactSafetyError,
    ArtifactStore,
    canonical_json,
)
from agent_world.contracts import DirectRun, EnvironmentRequest, RegistryReceipt
from agent_world.observe import ObserveError, observe_run


def _registry_receipt(state_root: Path, store: ArtifactStore, package: bytes) -> RegistryReceipt:
    package_digest = f"sha256:{sha256(package).hexdigest()}"
    receipt = {
        "status": "released",
        "package_id": "package_demo",
        "version": "v1",
        "package_digest": package_digest,
    }
    receipt_body = canonical_json(receipt)
    receipt_digest = f"sha256:{sha256(receipt_body).hexdigest()}"
    receipt_ref = store.put_json("registry.receipt", receipt)

    receipts = state_root / "registry" / "receipts"
    packages = state_root / "registry" / "packages"
    receipts.mkdir(parents=True)
    packages.mkdir(parents=True)
    (receipts / f"{receipt_digest.removeprefix('sha256:')}.json").write_bytes(receipt_body)
    (packages / f"{package_digest.removeprefix('sha256:')}.zip").write_bytes(package)
    return RegistryReceipt(
        package_id="package_demo",
        version="v1",
        package_digest=package_digest,
        receipt_digest=receipt_digest,
        artifact=receipt_ref,
    )


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


def test_observe_requires_registry_receipt_and_package_recheck(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    request = EnvironmentRequest.create("Track an inventory handoff")
    run = DirectRun.create(request)
    store = ArtifactStore(state_root / "runs" / run.run_id)
    receipt = _registry_receipt(state_root, store, b"package bytes")
    run.finish("released", receipt=receipt)
    store.write_run(run)

    scene = observe_run(state_root, run.run_id)
    assert scene["release"]["status"] == "released"
    assert scene["release"]["package_id"] == "package_demo"

    package_path = state_root / "registry" / "packages" / f"{receipt.package_digest[7:]}.zip"
    package_path.write_bytes(b"tampered package")

    assert observe_run(state_root, run.run_id)["release"] == {"status": "not_published"}

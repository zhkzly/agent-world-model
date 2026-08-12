"""Read-only, secret-safe projection of a persisted Direct run."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_world.artifacts import ArtifactIntegrityError, ArtifactStore, canonical_json
from agent_world.candidate import CandidateError, _cold_read_package
from agent_world.contracts import ArtifactRef
from agent_world.graph import candidate_graph, design_graph

_RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9_-]+\Z")
_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})\Z")
_PACKAGE_REF_KEYS = {
    "package_id",
    "version",
    "package_digest",
    "manifest_digest",
    "registry_receipt_ref",
    "design_ref",
    "candidate_manifest_ref",
    "integration_ref",
    "judge_report_ref",
    "semantic_lineage_ref",
    "implementation_lineage_ref",
}


class ObserveError(ValueError):
    pass


def _digest_hex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DIGEST_PATTERN.fullmatch(value)
    return match.group(1) if match is not None else None


def _artifact_ref(value: object) -> ArtifactRef | None:
    if not isinstance(value, dict) or set(value) != {
        "artifact_id",
        "kind",
        "digest",
        "path",
        "media_type",
    }:
        return None
    try:
        return ArtifactRef(**value)
    except TypeError:
        return None


def _ref_value(ref: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_id": ref.artifact_id,
        "kind": ref.kind,
        "digest": ref.digest,
        "path": ref.path,
        "media_type": ref.media_type,
    }


def _payload(store: ArtifactStore, ref: ArtifactRef) -> Any:
    value = store.read_json(ref)
    if isinstance(value, dict) and "producer" in value:
        return store.read_envelope(ref)["payload"]
    return value


def _released_fact(
    state_root: Path, store: ArtifactStore, release: object
) -> dict[str, str] | None:
    """Cold-read the Registry receipt and the same complete package closure."""

    if not isinstance(release, dict) or set(release) != _PACKAGE_REF_KEYS:
        return None
    package_digest = release.get("package_digest")
    manifest_digest = release.get("manifest_digest")
    package_hex = _digest_hex(package_digest)
    manifest_hex = _digest_hex(manifest_digest)
    receipt_ref = _artifact_ref(release.get("registry_receipt_ref"))
    if (
        not isinstance(package_digest, str)
        or package_hex is None
        or manifest_hex is None
        or receipt_ref is None
    ):
        return None
    refs: dict[str, ArtifactRef] = {}
    for key in (
        "design_ref",
        "candidate_manifest_ref",
        "integration_ref",
        "judge_report_ref",
        "semantic_lineage_ref",
        "implementation_lineage_ref",
    ):
        ref = _artifact_ref(release.get(key))
        if ref is None:
            return None
        refs[key] = ref
    try:
        receipt = _payload(store, receipt_ref)
        if isinstance(receipt, dict) and "receipt" in receipt:
            receipt = receipt["receipt"]
        receipt_body = canonical_json(receipt)
        receipt_hex = sha256(receipt_body).hexdigest()
        package_body = (state_root / "registry" / "packages" / f"{package_hex}.zip").read_bytes()
        disk_receipt = (state_root / "registry" / "receipts" / f"{receipt_hex}.json").read_bytes()
        package = _cold_read_package(package_body, package_digest)
        manifest = package["manifest"]
        metadata = package["metadata"]
        manifest_digest_value = package["manifest_digest"]
        artifact_refs = manifest["artifact_refs"]
        verifier_ref = _artifact_ref(artifact_refs.get("verifier"))
        dossier_ref = _artifact_ref(artifact_refs.get("dossier"))
        telemetry_ref = _artifact_ref(artifact_refs.get("telemetry"))
        if verifier_ref is None or dossier_ref is None or telemetry_ref is None:
            return None
        design = _payload(store, refs["design_ref"])
        candidate = _payload(store, refs["candidate_manifest_ref"])
        integration = _payload(store, refs["integration_ref"])
        judge = _payload(store, refs["judge_report_ref"])
        verifier = _payload(store, verifier_ref)
        dossier = _payload(store, dossier_ref)
        telemetry = _payload(store, telemetry_ref)
        semantic_lineage = _payload(store, refs["semantic_lineage_ref"])
        implementation_lineage = _payload(store, refs["implementation_lineage_ref"])
    except (
        ArtifactIntegrityError,
        CandidateError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None
    if (
        f"sha256:{sha256(package_body).hexdigest()}" != package_digest
        or manifest_digest_value != manifest_digest
        or disk_receipt != receipt_body
        or not isinstance(receipt, dict)
        or set(receipt)
        != {
            "package_id",
            "version",
            "package_digest",
            "manifest_digest",
            "registry_revision",
            "published_at",
        }
        or receipt["package_id"] != release.get("package_id")
        or receipt["version"] != release.get("version")
        or receipt["package_digest"] != package_digest
        or receipt["manifest_digest"] != manifest_digest
        or not all(
            isinstance(value, dict)
            for value in (
                design,
                candidate,
                integration,
                judge,
                verifier,
                dossier,
                telemetry,
                semantic_lineage,
                implementation_lineage,
            )
        )
    ):
        return None
    assert isinstance(verifier, dict)
    contract_refs = {
        "design": refs["design_ref"],
        "candidate": refs["candidate_manifest_ref"],
        "integration": refs["integration_ref"],
        "judge": refs["judge_report_ref"],
        "verifier": verifier_ref,
        "dossier": dossier_ref,
        "telemetry": telemetry_ref,
        "semantic_lineage": refs["semantic_lineage_ref"],
        "implementation_lineage": refs["implementation_lineage_ref"],
    }
    candidate_manifest = candidate.get("manifest")
    if manifest.get("artifact_refs") != {
        name: _ref_value(ref) for name, ref in contract_refs.items()
    } or manifest.get("contract_digests") != {
        name: ref.digest for name, ref in contract_refs.items()
    }:
        return None
    gates = _judge_gates(judge)
    if gates is None or not isinstance(candidate_manifest, dict):
        return None
    assurance = metadata.get("evidence/assurance.json")
    try:
        gate_evidence = [
            store.read_json(ArtifactRef(**gate["evidence"])) for gate in judge["gates"]
        ]
    except (ArtifactIntegrityError, KeyError, TypeError, ValueError):
        return None
    if (
        manifest.get("origin") != "direct"
        or manifest.get("parent_package_refs") != []
        or integration.get("status") != "passed"
        or integration.get("admitted_lock_closure") != manifest.get("dependency_closure")
        or judge.get("integration_ref") != _ref_value(refs["integration_ref"])
        or judge.get("verifier_ref") != _ref_value(verifier_ref)
        or not isinstance(verifier.get("commitments"), list)
        or not verifier.get("commitments")
        or verifier.get("commitment_count") != len(verifier["commitments"])
        or dossier
        != {
            "schema_version": "release-dossier@1",
            "artifact_refs": {
                name: _ref_value(ref) for name, ref in contract_refs.items() if name != "dossier"
            },
            "integration_status": "passed",
            "judge_gates": gates,
        }
        or telemetry != metadata.get("evidence/telemetry.json")
        or metadata.get("evidence/provenance.json")
        != {
            "schema_version": "provenance@1",
            "input_refs": {name: _ref_value(ref) for name, ref in contract_refs.items()},
            "semantic_lineage_ref": _ref_value(refs["semantic_lineage_ref"]),
            "implementation_lineage_ref": _ref_value(refs["implementation_lineage_ref"]),
        }
        or not _assurance_matches(
            assurance,
            refs["integration_ref"],
            refs["judge_report_ref"],
            dossier_ref,
            gates,
            gate_evidence,
            candidate_manifest.get("source_digest"),
        )
        or not isinstance(metadata.get("evidence/fidelity.json"), dict)
        or metadata["evidence/fidelity.json"].get("reality_equivalence") != "not_claimed"
        or semantic_lineage
        != {
            "origin": "direct",
            "parent_package_refs": [],
            "design_ref": _ref_value(refs["design_ref"]),
        }
        or implementation_lineage
        != {
            "candidate_manifest_ref": _ref_value(refs["candidate_manifest_ref"]),
            "source_digest": candidate_manifest.get("source_digest"),
        }
        or manifest.get("source_digest") != candidate_manifest.get("source_digest")
        or manifest.get("source_files") != candidate_manifest.get("files")
    ):
        return None
    return {
        "status": "released",
        "package_id": receipt["package_id"],
        "version": receipt["version"],
        "package_digest": package_digest,
        "manifest_digest": manifest_digest,
        "registry_revision": receipt["registry_revision"],
    }


def _assurance_matches(
    assurance: object,
    integration_ref: ArtifactRef,
    judge_ref: ArtifactRef,
    dossier_ref: ArtifactRef,
    gates: list[dict[str, Any]],
    gate_evidence: list[Any],
    candidate_digest: object,
) -> bool:
    """Verify complete safe family/tool coverage without exposing rule values."""

    if (
        not isinstance(assurance, dict)
        or set(assurance)
        != {
            "schema_version",
            "passed_integration_ref",
            "judge_report_ref",
            "release_dossier_ref",
            "judge_gates",
            "integration_coverage",
            "judge_coverage",
            "public_commitment_bindings",
        }
        or assurance["schema_version"] != "assurance@1"
        or assurance["passed_integration_ref"] != _ref_value(integration_ref)
        or assurance["judge_report_ref"] != _ref_value(judge_ref)
        or assurance["release_dossier_ref"] != _ref_value(dossier_ref)
        or assurance["judge_gates"] != gates
        or not isinstance(assurance["integration_coverage"], list)
        or not isinstance(assurance["judge_coverage"], list)
        or not isinstance(assurance["public_commitment_bindings"], list)
        or not isinstance(candidate_digest, str)
        or len(gate_evidence) != len(gates)
    ):
        return False
    recipes: dict[tuple[int, int], str] = {}
    for coverage in assurance["integration_coverage"]:
        if (
            not isinstance(coverage, dict)
            or set(coverage) != {"task_family_index", "tool_index", "recipe_digest"}
            or type(coverage["task_family_index"]) is not int
            or type(coverage["tool_index"]) is not int
            or not isinstance(coverage["recipe_digest"], str)
        ):
            return False
        pair = (coverage["task_family_index"], coverage["tool_index"])
        if pair in recipes:
            return False
        recipes[pair] = coverage["recipe_digest"]
    if not recipes:
        return False
    expected_gate_ids = [
        gate_id
        for family, tool in recipes
        for gate_id in (
            f"task_materialization:{family}:{tool}",
            f"task_reachability:{family}:{tool}",
        )
    ]
    for commitment in assurance["public_commitment_bindings"]:
        if not isinstance(commitment, dict) or not isinstance(commitment.get("commitment_id"), str):
            return False
        expected_gate_ids.append(commitment["commitment_id"])
    return (
        [gate["gate_id"] for gate in gates] == expected_gate_ids
        and assurance["judge_coverage"]
        == [{"gate_id": gate["gate_id"], "evidence_ref": gate["evidence_ref"]} for gate in gates]
        and all(
            isinstance(evidence, dict)
            and set(evidence) == {"gate_id", "status", "code", "candidate_digest", "binding"}
            and evidence["gate_id"] == gate["gate_id"]
            and evidence["status"] == "passed"
            and evidence["code"] == gate["code"]
            and evidence["candidate_digest"] == candidate_digest
            and isinstance(evidence["binding"], dict)
            and set(evidence["binding"]) == {"task_family_index", "tool_index", "recipe_digest"}
            and type(evidence["binding"]["task_family_index"]) is int
            and type(evidence["binding"]["tool_index"]) is int
            and recipes.get(
                (evidence["binding"]["task_family_index"], evidence["binding"]["tool_index"])
            )
            == evidence["binding"]["recipe_digest"]
            for gate, evidence in zip(gates, gate_evidence, strict=True)
        )
    )


def _judge_gates(judge: dict[str, Any]) -> list[dict[str, Any]] | None:
    gates = judge.get("gates")
    if not isinstance(gates, list) or not gates:
        return None
    projected: list[dict[str, Any]] = []
    for gate in gates:
        if not isinstance(gate, dict) or set(gate) != {"gate_id", "status", "code", "evidence"}:
            return None
        evidence = _artifact_ref(gate["evidence"])
        if evidence is None or gate["status"] != "passed":
            return None
        projected.append(
            {
                "gate_id": gate["gate_id"],
                "status": gate["status"],
                "code": gate["code"],
                "evidence_ref": _ref_value(evidence),
            }
        )
    return projected


def _work_projection(store: ArtifactStore, work_refs: object) -> list[dict[str, Any]]:
    """Project the ordered persisted WorkRecords, never coarse pseudo-stages."""

    refs: dict[str, ArtifactRef] = {}
    if isinstance(work_refs, list):
        for item in work_refs:
            ref = _artifact_ref(item)
            if ref is not None and ref.kind == "control.work_record":
                refs[ref.digest] = ref
    for path in store.artifacts_root.glob("*.json"):
        try:
            value = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("kind") != "control.work_record":
            continue
        digest = f"sha256:{path.stem}"
        refs[digest] = ArtifactRef(
            artifact_id=f"control.work_record:{path.stem[:16]}",
            kind="control.work_record",
            digest=digest,
            path=str(path.relative_to(store.run_root)),
        )

    order = {
        (graph.graph_id, node.id): (graph_index, node_index)
        for graph_index, graph in enumerate((design_graph(), candidate_graph()))
        for node_index, node in enumerate(graph.nodes)
    }
    records: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for ref in refs.values():
        try:
            record = store.read_json(ref)
        except ArtifactIntegrityError:
            continue
        coordinate = record.get("coordinate") if isinstance(record, dict) else None
        if not isinstance(coordinate, dict):
            continue
        projection = {
            "graph": coordinate.get("graph_id"),
            "node": coordinate.get("node_id"),
            "shard": coordinate.get("shard_key"),
            "revision": coordinate.get("revision"),
            "owner": record.get("owner"),
            "execution_kind": record.get("execution_kind"),
            "status": record.get("status"),
            "safe_code": record.get("safe_code"),
            "dependency_ids": [
                item.get("artifact_id") for item in record.get("dependency_refs", [])
            ],
            "output_ids": [item.get("artifact_id") for item in record.get("output_refs", [])],
            "finding_ids": [item.get("artifact_id") for item in record.get("finding_refs", [])],
        }
        records.append(
            (
                (
                    *order.get((projection["graph"], projection["node"]), (99, 99)),
                    projection["shard"] or "",
                    projection["revision"],
                    ref.digest,
                ),
                projection,
            )
        )
    return [projection for _, projection in sorted(records)]


def _findings_projection(store: ArtifactStore) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(store.artifacts_root.glob("*.json")):
        try:
            value = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("kind") != "control.finding":
            continue
        digest = f"sha256:{path.stem}"
        ref = ArtifactRef(
            artifact_id=f"control.finding:{path.stem[:16]}",
            kind="control.finding",
            digest=digest,
            path=str(path.relative_to(store.run_root)),
        )
        try:
            finding = store.read_json(ref)
        except ArtifactIntegrityError:
            continue
        if not isinstance(finding, dict):
            continue
        subject = _artifact_ref(finding.get("subject_ref"))
        evidence = finding.get("evidence_refs")
        if subject is None or not isinstance(evidence, list):
            continue
        evidence_ids: list[str] = []
        for item in evidence:
            evidence_ref = _artifact_ref(item)
            if evidence_ref is None:
                break
            evidence_ids.append(evidence_ref.artifact_id)
        else:
            findings.append(
                {
                    "finding_id": finding.get("finding_id"),
                    "owner": finding.get("owner"),
                    "code": finding.get("code"),
                    "category": finding.get("category"),
                    "severity": finding.get("severity"),
                    "expected_condition": finding.get("expected_condition"),
                    "blocks_release": finding.get("blocks_release"),
                    "subject_id": subject.artifact_id,
                    "evidence_ids": evidence_ids,
                }
            )
            continue
    return findings


def observe_run(state_root: Path, run_id: str) -> dict[str, Any]:
    """Return safe facts only; this function never creates or changes state."""

    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ObserveError("observe_scope_not_found")
    store = ArtifactStore(state_root / "runs" / run_id)
    try:
        run = store.read_run()
    except ArtifactIntegrityError as exc:
        raise ObserveError("observe_scope_not_found") from exc

    release = (
        _released_fact(state_root, store, run.get("release"))
        if run.get("status") == "released"
        else None
    )
    events = [
        {
            "stage": event.get("stage"),
            "status": event.get("status"),
            "code": event.get("code"),
        }
        for event in run.get("events", [])
        if isinstance(event, dict) and event.get("stage") in {"intake", "run"}
    ]
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "request": {
            "request_id": run.get("request_id"),
            "digest": run.get("request_digest"),
        },
        "events": events,
        "terminal_code": next(
            (event["code"] for event in reversed(events) if event["stage"] == "run"), None
        ),
        "works": _work_projection(store, run.get("work_records")),
        "findings": _findings_projection(store),
        "release": release if release is not None else {"status": "not_published"},
    }

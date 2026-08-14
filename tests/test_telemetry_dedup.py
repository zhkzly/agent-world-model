from __future__ import annotations

from pathlib import Path

from agent_world import candidate as candidate_module
from agent_world.artifacts import ArtifactStore
from agent_world.contracts import ArtifactRef, WorkCoordinate


def _digest() -> str:
    return "sha256:" + "a" * 64


def _operation(store: ArtifactStore, category: str) -> ArtifactRef:
    ref = store.put_json(
        "assurance.operation",
        {
            "category": category,
            "node_id": "research_acquire",
            "model": None,
            "usage": None,
            "skill_digest": None,
        },
    )
    return ArtifactRef(ref.artifact_id, ref.kind, ref.digest, ref.path)


def _work(store: ArtifactStore, graph: str, node: str, ops: tuple[ArtifactRef, ...]) -> ArtifactRef:
    return store.put_json(
        "control.work_record",
        {
            "coordinate": {
                "graph_id": graph,
                "node_id": node,
                "revision": 1,
                "run_id": "telemetry-run",
                "shard_key": None,
            },
            "status": "passed",
            "assurance_refs": [
                {
                    "artifact_id": ref.artifact_id,
                    "kind": ref.kind,
                    "digest": ref.digest,
                    "path": ref.path,
                }
                for ref in ops
            ],
            "dependency_refs": [],
            "output_refs": [],
            "semantic_revision_digest": _digest(),
        },
    )


def test_telemetry_dedup_within_work_and_across_works(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    fetch = _operation(store, "fetch")
    extract = _operation(store, "extract")
    search = _operation(store, "search")
    # One work lists the same fetch/extract digests repeatedly (one per source).
    acquire = _work(store, "design", "research_acquire", (search, fetch, extract, fetch, extract, fetch))
    # A second distinct work (candidate graph) lists the same fetch digest
    # (a different real op).
    other = _work(store, "candidate", "other_node", (fetch,))
    value = candidate_module._compile_telemetry(store, (acquire, acquire), (other,))
    assert set(value) == {"schema_version", "category_counts", "model_counts", "operations"}
    assert value["schema_version"] == "telemetry-release-summary@1"
    fetched = [item for item in value["operations"] if item["category"] == "fetch"]
    assert len(fetched) == 2  # once per work, never twice within one work
    extracted = [item for item in value["operations"] if item["category"] == "extract"]
    assert len(extracted) == 1
    searched = [item for item in value["operations"] if item["category"] == "search"]
    assert len(searched) == 1
    counts = {item["category"]: item["count"] for item in value["category_counts"]}
    assert counts == {"fetch": 2, "extract": 1, "search": 1}

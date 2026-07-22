"""Materialize real fetched research into immutable evidence Artifacts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, Evidence
from agent_world.research import ResearchBundle
from agent_world.research.security import assert_safe_research_document


def materialize_research_evidence(
    *,
    job_id: str,
    bundle: ResearchBundle,
    artifacts: ArtifactWriter,
) -> tuple[tuple[Evidence, ...], tuple[ArtifactRef, ...]]:
    """Write raw/metadata/extracted source closures before admitting Evidence."""

    evidence: list[Evidence] = []
    all_refs: list[ArtifactRef] = []
    for index, document in enumerate(bundle.documents):
        assert_safe_research_document(document)
        suffix = document.raw_sha256[:20]
        raw_ref = artifacts.put_blob(
            artifact_id=f"{job_id}:source-raw:{suffix}",
            artifact_type="evidence.raw_content",
            content=document.source.body,
            media_type=document.source.media_type,
        )
        metadata = {
            "requested_url": document.source.requested_url,
            "final_url": document.source.final_url,
            "fetched_at": document.source.fetched_at.isoformat(),
            "status_code": document.source.status_code,
            "media_type": document.source.media_type,
            "response_headers": list(document.source.response_headers),
            "fetcher": document.source.fetcher,
            "network_assurance": document.source.network_assurance,
            "resolved_addresses": list(document.source.resolved_addresses),
        }
        metadata_ref = artifacts.put_json(
            artifact_id=f"{job_id}:source-meta:{suffix}",
            artifact_type="evidence.response_metadata",
            value=metadata,
            dependencies=(raw_ref,),
        )
        content_ref = artifacts.put_blob(
            artifact_id=f"{job_id}:source-text:{document.text_sha256[:20]}",
            artifact_type="evidence.extracted_content",
            content=document.text.encode("utf-8"),
            media_type="text/plain;charset=utf-8",
            dependencies=(raw_ref, metadata_ref),
        )
        evidence.append(
            Evidence(
                evidence_id=_stable_id(
                    "evidence", document.source.final_url, document.text_sha256, str(index)
                ),
                source_kind="web",
                source_uri=document.source.final_url,
                retrieved_at=document.source.fetched_at,
                retrieval_status="success",
                raw_content_hash=f"sha256:{document.raw_sha256}",
                content_hash=f"sha256:{document.text_sha256}",
                fetcher=document.source.fetcher,
                fetcher_version="agent-world-0.2",
                extractor=document.extractor,
                extractor_version=document.extractor_version,
                title=document.title,
                source_risk="medium",
                observed_summary=re.sub(r"\s+", " ", document.text).strip()[:600],
                content_ref=content_ref,
                raw_content_ref=raw_ref,
                response_metadata_ref=metadata_ref,
            )
        )
        all_refs.extend((raw_ref, metadata_ref, content_ref))
    return tuple(evidence), _unique_refs(all_refs)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _unique_refs(refs: Sequence[ArtifactRef]) -> tuple[ArtifactRef, ...]:
    return tuple({ref.revision_id: ref for ref in refs}.values())


__all__ = ["materialize_research_evidence"]

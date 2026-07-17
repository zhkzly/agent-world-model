from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Evidence, EvidencePassage
from agent_world.designer.service import EnvironmentDesigner
from agent_world.research import (
    ExtractedDocument,
    FetchedDocument,
    ResearchBundle,
    build_evidence_passage_pack,
)


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _inputs() -> tuple[tuple[Evidence, ...], ResearchBundle, tuple[str, ...]]:
    texts = (
        ("prefix material. " * 100)
        + "A repeated completion is idempotent and preserves completed state."
        + (" suffix. " * 100),
        ("other documentation. " * 80)
        + "An unknown identifier returns a structured not_found result without mutation."
        + (" tail. " * 80),
    )
    evidence: list[Evidence] = []
    documents: list[ExtractedDocument] = []
    for index, text in enumerate(texts):
        raw = text.encode()
        source = FetchedDocument(
            requested_url=f"https://example.test/{index}",
            final_url=f"https://example.test/{index}",
            fetched_at=datetime.now(UTC),
            status_code=200,
            media_type="text/plain",
            body=raw,
        )
        documents.append(
            ExtractedDocument(
                source=source,
                text=text,
                title=f"Source {index}",
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                text_sha256=hashlib.sha256(raw).hexdigest(),
                extractor="test-extractor",
                extractor_version="1",
            )
        )
        evidence.append(
            Evidence(
                evidence_id=f"evidence:{index}",
                source_kind="web",
                source_uri=source.final_url,
                retrieved_at=source.fetched_at,
                retrieval_status="success",
                raw_content_hash=_hash(text),
                content_hash=_hash(text),
                fetcher="test-fetcher",
                fetcher_version="1",
                extractor="test-extractor",
                extractor_version="1",
                title=f"Source {index}",
                observed_summary="catalog preview",
            )
        )
    return (
        tuple(evidence),
        ResearchBundle(
            searches=(),
            documents=tuple(documents),
            failures=(),
            search_calls=0,
            fetch_calls=2,
        ),
        texts,
    )


def test_passage_pack_is_deterministic_bounded_and_source_auditable() -> None:
    evidence, bundle, texts = _inputs()
    first = build_evidence_passage_pack(
        pack_id="passage-pack:test",
        need="idempotent completion and unknown todo not_found without mutation",
        query_texts=("completion idempotency", "unknown identifier not_found"),
        evidence=evidence,
        bundle=bundle,
    )
    second = build_evidence_passage_pack(
        pack_id="passage-pack:test",
        need="idempotent completion and unknown todo not_found without mutation",
        query_texts=("completion idempotency", "unknown identifier not_found"),
        evidence=evidence,
        bundle=bundle,
    )

    assert first == second
    assert first.source_count == 2
    assert {item.evidence_id for item in first.passages} == {"evidence:0", "evidence:1"}
    assert any("idempotent" in item.text for item in first.passages)
    assert any("not_found" in item.text for item in first.passages)
    for passage in first.passages:
        source_index = int(passage.evidence_id.rsplit(":", 1)[1])
        assert texts[source_index][passage.start_char : passage.end_char] == passage.text
        assert passage.source_content_hash == evidence[source_index].content_hash


def test_passage_pack_rejects_tampered_source_hash() -> None:
    evidence, bundle, _texts = _inputs()
    tampered = (evidence[0].model_copy(update={"content_hash": "sha256:" + "0" * 64}), evidence[1])

    with pytest.raises(ValueError, match="source hash mismatch"):
        build_evidence_passage_pack(
            pack_id="passage-pack:tampered",
            need="idempotency",
            query_texts=(),
            evidence=tampered,
            bundle=bundle,
        )


def test_passage_contract_rejects_text_outside_its_hash() -> None:
    with pytest.raises(ValidationError, match="hash does not match"):
        EvidencePassage(
            passage_id="passage:tampered",
            evidence_id="evidence:0",
            source_uri="https://example.test/0",
            source_content_hash="sha256:" + "1" * 64,
            start_char=0,
            end_char=4,
            passage_hash="sha256:" + "2" * 64,
            text="text",
        )


def test_passage_pack_binds_trimmed_html_text_to_exact_source_offsets() -> None:
    text = "\n  Hotel booking requires arrival and departure dates.\n\n"
    raw = text.encode()
    source = FetchedDocument(
        requested_url="https://example.test/hotel",
        final_url="https://example.test/hotel",
        fetched_at=datetime.now(UTC),
        status_code=200,
        media_type="text/html",
        body=raw,
    )
    document = ExtractedDocument(
        source=source,
        text=text,
        title="Hotel",
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(raw).hexdigest(),
        extractor="trafilatura-subprocess",
        extractor_version="1",
    )
    evidence = Evidence(
        evidence_id="evidence:hotel",
        source_kind="web",
        source_uri=source.final_url,
        retrieved_at=source.fetched_at,
        retrieval_status="success",
        raw_content_hash=_hash(text),
        content_hash=_hash(text),
        fetcher="http",
        fetcher_version="1",
        extractor=document.extractor,
        extractor_version="1",
        observed_summary="catalog preview",
    )

    pack = build_evidence_passage_pack(
        pack_id="passage-pack:hotel",
        need="hotel booking",
        query_texts=(),
        evidence=(evidence,),
        bundle=ResearchBundle(
            searches=(),
            documents=(document,),
            failures=(),
            search_calls=0,
            fetch_calls=1,
        ),
    )

    passage = pack.passages[0]
    assert passage.text == "Hotel booking requires arrival and departure dates."
    assert text[passage.start_char : passage.end_char] == passage.text


def test_research_materialization_deduplicates_shared_raw_revision_dependencies(
    tmp_path: Path,
) -> None:
    text = "The same hotel policy is syndicated by two independently fetched URLs."
    raw = text.encode()
    raw_hash = hashlib.sha256(raw).hexdigest()
    fetched_at = datetime.now(UTC)
    documents = tuple(
        ExtractedDocument(
            source=FetchedDocument(
                requested_url=f"https://example.test/hotel-policy-{index}",
                final_url=f"https://example.test/hotel-policy-{index}",
                fetched_at=fetched_at,
                status_code=200,
                media_type="text/plain",
                body=raw,
            ),
            text=text,
            title=f"Hotel policy mirror {index}",
            raw_sha256=raw_hash,
            text_sha256=raw_hash,
            extractor="trafilatura-subprocess",
            extractor_version="1",
        )
        for index in range(2)
    )
    store = ArtifactStore(tmp_path / "artifacts")
    research_writer = store.issue_writer(
        producer="researcher",
        allowed_artifact_type_prefixes=("evidence.",),
    )
    store.seal_capability_issuance()
    designer = object.__new__(EnvironmentDesigner)
    designer.research_artifacts = research_writer

    evidence, source_refs = designer.materialize_research_evidence(
        "generate-job:hotel",
        ResearchBundle(
            searches=(),
            documents=documents,
            failures=(),
            search_calls=0,
            fetch_calls=2,
        ),
    )

    assert len(evidence) == 2
    assert len({ref.revision_id for ref in source_refs}) == len(source_refs)
    assert len(source_refs) == 5

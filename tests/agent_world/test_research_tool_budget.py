from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.contracts import ArtifactRef, PermissionScope, sha256_digest
from agent_world.control import TelemetryStore
from agent_world.research import (
    ExtractedDocument,
    FetchedDocument,
    ResearchEvidenceUnavailable,
    ResearchToolchain,
    SearchHit,
    SearchQuery,
    SearchRecord,
    SearchUpstreamFailure,
)
from agent_world.research.models import FetchFailure, ResearchBundle
from agent_world.research.providers import _searxng_upstream_failures


class CountedSearchTransport:
    name = "counted-search-transport"

    def __init__(self) -> None:
        self.calls = 0

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del credential_handles
        self.calls += 1
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=datetime.now(UTC),
            raw_response_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
            hits=tuple(
                SearchHit(
                    url=f"https://source-{index}.example.test/document",
                    title=f"Source {index}",
                    snippet="candidate only",
                )
                for index in range(limit)
            ),
        )


class EmptySearchTransport(CountedSearchTransport):
    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del limit, credential_handles
        self.calls += 1
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=datetime.now(UTC),
            raw_response_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
            hits=(),
        )


class UnavailableSearchTransport(CountedSearchTransport):
    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del query, limit, credential_handles
        self.calls += 1
        raise RuntimeError("provider request leaked-query=must-not-cross-boundary")


class PartiallyDegradedEmptySearchTransport(CountedSearchTransport):
    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del limit, credential_handles
        self.calls += 1
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=datetime.now(UTC),
            raw_response_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
            hits=(),
            upstream_failures=(SearchUpstreamFailure(engine="one-engine", reason="timeout"),),
        )


class ConcurrentEmptySearchTransport(EmptySearchTransport):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.maximum_active = 0

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().search(
                query,
                limit=limit,
                credential_handles=credential_handles,
            )
        finally:
            self.active -= 1


class CountedFetchTransport:
    name = "counted-fetch-transport"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(
        self,
        url: str,
        *,
        source_policy: object | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument:
        del source_policy, credential_handles
        self.calls += 1
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            status_code=200,
            media_type="text/plain",
            body=(f"Evidence from {url}. " * 20).encode(),
            fetcher=self.name,
            network_assurance="protocol-meter-test",
        )


class SelectiveFailureFetchTransport(CountedFetchTransport):
    async def fetch(
        self,
        url: str,
        *,
        source_policy: object | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument:
        if "credential" in url:
            self.calls += 1
            raise RuntimeError(f"fetch failed for {url}; secret=sk-do-not-persist")
        return await super().fetch(
            url,
            source_policy=source_policy,
            credential_handles=credential_handles,
        )


class CountedExtractor:
    name = "counted-extractor"

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, source: FetchedDocument) -> ExtractedDocument:
        self.calls += 1
        text = source.body.decode()
        return ExtractedDocument(
            source=source,
            text=text,
            title=None,
            raw_sha256=hashlib.sha256(source.body).hexdigest(),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            extractor=self.name,
            extractor_version="1",
        )


def _ref(name: str, artifact_type: str) -> ArtifactRef:
    digest = sha256_digest(name.encode())
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=1,
    )


def test_searxng_upstream_failures_are_bounded_and_typed() -> None:
    failures = _searxng_upstream_failures(
        [["bing", "timeout"], ["brave", "Suspended: rate limit"], ["invalid"]]
    )

    assert failures == (
        SearchUpstreamFailure(engine="bing", reason="timeout"),
        SearchUpstreamFailure(engine="brave", reason="Suspended: rate limit"),
    )


def test_research_unavailable_summary_distinguishes_search_from_fetch_attrition() -> None:
    query = SearchQuery("hotel booking")
    search = SearchRecord(
        query=query,
        provider="test",
        requested_at=datetime.now(UTC),
        raw_response_sha256="0" * 64,
        hits=(),
        upstream_failures=(SearchUpstreamFailure(engine="bing", reason="timeout"),),
    )
    bundle = ResearchBundle(
        searches=(search,),
        documents=(),
        failures=(
            FetchFailure.redacted(
                stage="search",
                error_type="SearchUpstreamUnavailable",
                identity="hotel booking",
                message="safe aggregate",
            ),
        ),
        search_calls=1,
        fetch_calls=0,
        extract_calls=0,
    )

    summary = bundle.evidence_unavailable_summary()

    assert "hits=0" in summary
    assert "fetch_calls=0" in summary
    assert "upstream_failures=1" in summary
    assert "search/SearchUpstreamUnavailable=1" in summary


@pytest.mark.asyncio
async def test_no_evidence_preserves_typed_reason_and_observed_calls() -> None:
    empty = ResearchToolchain(
        EmptySearchTransport(),
        CountedFetchTransport(),
        CountedExtractor(),
    )
    with pytest.raises(ResearchEvidenceUnavailable) as empty_failure:
        await empty.run(
            (SearchQuery("hotel booking"),),
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web",),
            maximum_tool_calls=3,
            require_evidence=True,
        )
    assert empty_failure.value.reason == "true_empty"
    assert empty_failure.value.search_calls == 1
    assert empty_failure.value.fetch_calls == 0
    assert empty_failure.value.extract_calls == 0

    unavailable = ResearchToolchain(
        UnavailableSearchTransport(),
        CountedFetchTransport(),
        CountedExtractor(),
    )
    with pytest.raises(ResearchEvidenceUnavailable) as unavailable_failure:
        await unavailable.run(
            (SearchQuery("secret query must be hashed"),),
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web",),
            maximum_tool_calls=3,
            require_evidence=True,
        )
    assert unavailable_failure.value.reason == "upstream_unavailable"
    assert unavailable_failure.value.failure_code == (
        "research_infrastructure_upstream_unavailable"
    )
    assert unavailable_failure.value.search_calls == 1
    assert unavailable_failure.value.fetch_calls == 0
    assert unavailable_failure.value.extract_calls == 0
    assert "secret query" not in str(unavailable_failure.value)
    assert "must-not-cross-boundary" not in str(unavailable_failure.value)


@pytest.mark.asyncio
async def test_partial_search_attrition_is_degraded_empty_not_total_outage() -> None:
    toolchain = ResearchToolchain(
        PartiallyDegradedEmptySearchTransport(),
        CountedFetchTransport(),
        CountedExtractor(),
    )
    with pytest.raises(ResearchEvidenceUnavailable) as captured:
        await toolchain.run(
            (SearchQuery("hotel booking"),),
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web",),
            maximum_tool_calls=3,
            require_evidence=True,
        )
    assert captured.value.reason == "degraded_empty"


@pytest.mark.asyncio
async def test_partial_success_failure_projection_contains_only_hashes() -> None:
    secret_url = "https://credential.example.test/doc?token=sk-do-not-persist"  # noqa: S105

    class TwoHitSearch(CountedSearchTransport):
        async def search(
            self,
            query: SearchQuery,
            *,
            limit: int = 10,
            credential_handles: frozenset[str] = frozenset(),
        ) -> SearchRecord:
            del limit, credential_handles
            self.calls += 1
            return SearchRecord(
                query=query,
                provider=self.name,
                requested_at=datetime.now(UTC),
                raw_response_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
                hits=(
                    SearchHit(url=secret_url, title="bad", snippet="candidate"),
                    SearchHit(
                        url="https://safe.example.test/doc",
                        title="good",
                        snippet="candidate",
                    ),
                ),
            )

    bundle = await ResearchToolchain(
        TwoHitSearch(),
        SelectiveFailureFetchTransport(),
        CountedExtractor(),
        max_parallel_fetches=2,
    ).run(
        (SearchQuery("hotel booking"),),
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
        maximum_tool_calls=5,
        results_per_query=2,
        max_documents=2,
        require_evidence=True,
    )

    assert len(bundle.documents) == 1
    projection = str(asdict(bundle.failures[0]))
    assert bundle.failures[0].identity_sha256.startswith("sha256:")
    assert bundle.failures[0].message_sha256.startswith("sha256:")
    assert secret_url not in projection
    assert "sk-do-not-persist" not in projection


@pytest.mark.asyncio
async def test_research_records_each_real_search_fetch_and_extract_span(
    tmp_path: Path,
) -> None:
    telemetry = TelemetryStore(tmp_path / "telemetry", commit_batch_size=128)
    root = telemetry.start_span(
        trace_id="run:research-operations",
        component="controller",
        operation="node.design",
        run_id="run:research-operations",
    )
    telemetry.activate_trace(
        trace_id="run:research-operations",
        run_id="run:research-operations",
        parent_span_id=root.span_id,
    )
    toolchain = ResearchToolchain(
        CountedSearchTransport(),
        CountedFetchTransport(),
        CountedExtractor(),
        telemetry=telemetry,
    )
    query_text = "hotel booking requirements that must never enter telemetry"

    await toolchain.run(
        (SearchQuery(query_text),),
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
        maximum_tool_calls=3,
        results_per_query=1,
        max_documents=1,
    )
    root.finish(status="passed")
    inspected = telemetry.inspect_trace("run:research-operations")
    operations = [item["operation"] for item in inspected["spans"]]

    assert operations.count("research.search") == 1
    assert operations.count("research.fetch") == 1
    assert operations.count("research.extract") == 1
    assert inspected["summary"]["metrics_sum"]["research.search.calls"] == 1
    assert inspected["summary"]["metrics_sum"]["research.extract.calls"] == 1
    serialized = str(inspected)
    assert query_text not in serialized
    assert "https://source-0.example.test/document" not in serialized
    telemetry.close()


def test_research_checkpoint_reuse_is_observed_without_fake_tool_calls(
    tmp_path: Path,
) -> None:
    telemetry = TelemetryStore(tmp_path / "telemetry")
    root = telemetry.start_span(
        trace_id="run:research-reuse",
        component="controller",
        operation="node.design",
        run_id="run:research-reuse",
    )
    telemetry.activate_trace(
        trace_id="run:research-reuse",
        run_id="run:research-reuse",
        parent_span_id=root.span_id,
    )
    toolchain = ResearchToolchain(
        CountedSearchTransport(),
        CountedFetchTransport(),
        CountedExtractor(),
        telemetry=telemetry,
    )

    toolchain.record_checkpoint_reuse(
        checkpoint_ref=_ref("checkpoint:evidence", "design.phase_checkpoint"),
        evidence_graph_ref=_ref("graph:evidence", "design.evidence_graph"),
    )
    root.finish(status="passed")
    inspected = telemetry.inspect_trace("run:research-reuse")

    assert [
        item["operation"]
        for item in inspected["spans"]
        if item["component"] == "research"
    ] == ["research.checkpoint_reuse"]
    assert inspected["summary"]["unknown_measurements"] == {
        "research.documents.extracted": 1,
        "research.extract.calls": 1,
        "research.fetch.calls": 1,
        "research.search.calls": 1,
    }
    telemetry.close()


@pytest.mark.asyncio
async def test_research_meter_counts_all_search_fetch_and_extract_calls_exactly() -> None:
    search = CountedSearchTransport()
    fetch = CountedFetchTransport()
    extract = CountedExtractor()
    toolchain = ResearchToolchain(
        search,
        fetch,
        extract,
        max_parallel_fetches=9,
    )

    bundle = await toolchain.run(
        tuple(SearchQuery(f"query {index}") for index in range(3)),
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
        maximum_tool_calls=21,
        results_per_query=12,
        max_documents=12,
    )

    assert search.calls == bundle.search_calls == 3
    assert fetch.calls == bundle.fetch_calls == 9
    assert extract.calls == bundle.extract_calls == 9
    assert search.calls + fetch.calls + extract.calls == 21
    assert len(bundle.documents) == 9


@pytest.mark.asyncio
async def test_known_source_urls_are_fetched_before_empty_search_results() -> None:
    search = EmptySearchTransport()
    fetch = CountedFetchTransport()
    extract = CountedExtractor()
    toolchain = ResearchToolchain(
        search,
        fetch,
        extract,
        max_parallel_fetches=2,
    )
    known_urls = (
        "https://docs.example.test/authoritative-a",
        "https://docs.example.test/authoritative-b",
    )

    bundle = await toolchain.run(
        (SearchQuery("query with no hits"),),
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
        maximum_tool_calls=5,
        results_per_query=10,
        max_documents=2,
        seed_urls=known_urls,
    )

    assert search.calls == bundle.search_calls == 1
    assert fetch.calls == bundle.fetch_calls == 2
    assert extract.calls == bundle.extract_calls == 2
    assert tuple(item.source.requested_url for item in bundle.documents) == known_urls


@pytest.mark.asyncio
async def test_independent_search_queries_run_with_bounded_concurrency() -> None:
    search = ConcurrentEmptySearchTransport()
    fetch = CountedFetchTransport()
    toolchain = ResearchToolchain(
        search,
        fetch,
        CountedExtractor(),
        max_parallel_searches=3,
        max_parallel_fetches=1,
    )

    bundle = await toolchain.run(
        tuple(SearchQuery(f"parallel query {index}") for index in range(3)),
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
        maximum_tool_calls=5,
        max_documents=1,
        seed_urls=("https://docs.example.test/evidence",),
    )

    assert bundle.search_calls == 3
    assert search.maximum_active == 3

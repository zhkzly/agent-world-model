"""Slice 2 acceptance tests for real discovery, retained bytes, and Extract.

The local HTTP origin is a mechanical boundary fixture.  It exercises actual
HTTP requests, redirects, byte retention, and Crawl4AI extraction; it is not
product evidence and cannot make Research Brief-ready by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from agent_env_foundry.research import (
    EvidenceStore,
    ResearchBudget,
    ResearchConfig,
    ResearchTools,
    sanitize_url,
)

PAGE_BYTES = b"""<!doctype html>
<html><head><title>Reservation policy</title></head><body><main>
<h1>Reservation policy</h1>
<p>A confirmed reservation consumes one unit of capacity.</p>
<p>When capacity is zero, the request is refused without creating a reservation.</p>
<p>A confirmed reservation consumes one unit of capacity.</p>
</main></body></html>"""

FOCUSED_PAGE_BYTES = b"""<!doctype html>
<html>
<head>
<style>.issuance-deadline { display: none; }</style>
<script>const navigationIssuanceDeadline = true;</script>
</head>
<body>
<header>Issuance deadline header must not be evidence.</header>
<nav>Issuance deadline navigation must not be evidence.</nav>
<aside>Issuance deadline sidebar must not be evidence.</aside>
<main>
<p>The invoice issuance deadline is no later than 30 days after delivery.</p>
<p>The issuance deadline is measured from the delivery date.</p>
<p>A third issuance deadline passage makes truncation observable.</p>
<p>Payment becomes due only on the separately agreed payment date.</p>
</main>
<footer>Issuance deadline footer must not be evidence.</footer>
<noscript>Issuance deadline noscript must not be evidence.</noscript>
</body>
</html>"""

RAW_HEX_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


class _ResearchOrigin:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        parsed = urlsplit(str(request.url))
        self.requests.append(str(request.url))
        if parsed.path == "/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            origin = "https://research.test"
            payload = {
                "query": query,
                "results": [
                    {
                        "url": f"{origin}/redirect",
                        "title": "Reservation policy",
                        "content": "Discovery snippet must never become evidence.",
                    },
                    {
                        "url": f"{origin}/mirror",
                        "title": "Policy mirror",
                        "content": "The same bytes are also discoverable here.",
                    },
                ],
            }
            return httpx.Response(200, json=payload, request=request)
        if parsed.path == "/redirect":
            return httpx.Response(302, headers={"Location": "/source"}, request=request)
        if parsed.path in {"/source", "/mirror"}:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                stream=httpx.ByteStream(PAGE_BYTES),
                request=request,
            )
        if parsed.path == "/binary":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/octet-stream"},
                stream=httpx.ByteStream(b"\x00\x01not-html"),
                request=request,
            )
        if parsed.path == "/focused":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                stream=httpx.ByteStream(FOCUSED_PAGE_BYTES),
                request=request,
            )
        return httpx.Response(404, content=b"missing", request=request)


@pytest.fixture
def research_origin() -> tuple[str, _ResearchOrigin, httpx.Client]:
    origin = _ResearchOrigin()
    client = httpx.Client(transport=httpx.MockTransport(origin), follow_redirects=True)
    try:
        return "https://research.test", origin, client
    finally:
        # ResearchTools does not own injected clients; pytest process cleanup is
        # sufficient and avoids closing before the returned fixture is consumed.
        pass


def make_tools(root: Path, origin: str, client: httpx.Client, **budget: int) -> ResearchTools:
    return ResearchTools(
        store=EvidenceStore(root),
        config=ResearchConfig(searxng_url=origin, request_timeout_seconds=2.0),
        budget=ResearchBudget(**budget),
        http_client=client,
    )


def test_search_sources_is_discovery_only_with_exact_receipts_and_warning(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_search_calls=3)

    first = tools.search_sources(
        queries=[{"query": "  reservation   capacity  ", "focus": "NEED-002"}]
    )
    repeated = tools.search_sources(
        queries=[{"query": "reservation capacity", "focus": "NEED-002"}]
    )

    assert first["failures"] == []
    assert first["receipts"][0]["query"] == "  reservation   capacity  "
    assert first["receipts"][0]["focus"] == "NEED-002"
    assert first["candidates"][0]["rank"] == 1
    assert first["candidates"][0]["candidate_handle"] == "C1"
    assert "candidate_id" not in first["candidates"][0]
    assert first["candidates"][0]["discovery_only"] is True
    assert "never become evidence" in first["candidates"][0]["snippet"]
    assert repeated["warnings"][0]["code"] == "normalized_query_duplicate"
    assert repeated["remaining_budget"]["search_calls"] == 1
    assert RAW_HEX_ID.search(json.dumps(first, sort_keys=True)) is None


def test_read_sources_fetches_only_selected_candidate_and_binds_exact_bytes(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, handler, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=3)
    discovery = tools.search_sources(
        queries=[{"query": "reservation refusal", "focus": "NEED-002"}]
    )
    selected = discovery["candidates"][0]["candidate_handle"]
    unselected_url = discovery["candidates"][1]["url"]

    result = tools.read_sources(
        entries=[{"source": selected, "focus": "reservation capacity and sold-out refusal"}]
    )

    assert result["failures"] == []
    assert len(result["reads"]) == 1
    read = result["reads"][0]
    assert read["source_handle"] == "S1"
    assert read["final_url"].endswith("/source")
    assert read["media_type"] == "text/html"
    assert read["focus_result"]["status"] == "matched"
    assert read["passages"]
    assert [item["evidence_handle"] for item in read["passages"]] == ["E1", "E2"]
    assert "source_revision" not in read
    assert "extraction" not in read
    assert RAW_HEX_ID.search(json.dumps(result, sort_keys=True)) is None
    assert unselected_url not in handler.requests

    reopened_store = EvidenceStore(tmp_path / "evidence")
    revision_id = reopened_store.resolve_source_handle(read["source_handle"])
    retained = reopened_store.read_revision(revision_id)
    assert retained.body == PAGE_BYTES
    assert retained.body_digest == hashlib.sha256(PAGE_BYTES).hexdigest()
    evidence_revision_id, passage_id = reopened_store.resolve_evidence_handle("E1")
    assert evidence_revision_id == revision_id
    assert passage_id.startswith("passage-")


def test_source_revision_reread_never_uses_network_and_coalesces_literal_occurrences(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, handler, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=2)
    first = tools.read_sources(
        entries=[{"source": f"{origin}/source", "focus": "confirmed reservation consumes capacity"}]
    )
    source_handle = first["reads"][0]["source_handle"]
    request_count = len(handler.requests)

    reread = tools.read_sources(
        entries=[{"source": source_handle, "focus": "confirmed reservation consumes capacity"}]
    )

    assert reread["failures"] == []
    assert reread["reads"][0]["selection_kind"] == "source"
    assert len(handler.requests) == request_count
    assert reread["remaining_budget"]["fetches"] == 1
    repeated = [
        passage
        for passage in reread["reads"][0]["passages"]
        if "confirmed reservation consumes" in passage["text"]
    ]
    assert len(repeated) == 1
    assert repeated[0]["occurrence_count"] == 2


def test_exact_body_mirrors_are_related_without_semantic_merging(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=2)
    result = tools.read_sources(
        entries=[
            {"source": f"{origin}/source", "focus": "reservation capacity"},
            {"source": f"{origin}/mirror", "focus": "reservation capacity"},
        ]
    )
    first, second = result["reads"]

    first_revision = tools.store.read_revision(
        tools.store.resolve_source_handle(first["source_handle"])
    )
    second_revision = tools.store.read_revision(
        tools.store.resolve_source_handle(second["source_handle"])
    )
    assert first["source_handle"] != second["source_handle"]
    assert first_revision.body_digest == second_revision.body_digest
    assert first_revision.source_revision_id in second_revision.body_mirrors


def test_credentials_are_removed_from_results_and_run_scoped_artifacts(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    root = tmp_path / "evidence"
    tools = make_tools(root, origin, client, max_fetches=1)
    secret = "route-secret-value"
    url = f"{origin}/source?api_key={secret}&safe=visible"

    result = tools.read_sources(entries=[{"source": url, "focus": "reservation capacity"}])

    serialized = json.dumps(result, sort_keys=True)
    artifact_bytes = b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
    assert secret not in serialized
    assert secret.encode() not in artifact_bytes
    assert "safe=visible" in serialized
    assert "api_key=%5BREDACTED%5D" in serialized
    assert sanitize_url("https://alice:password@example.test/a?token=top-secret&x=1") == (
        "https://example.test/a?token=%5BREDACTED%5D&x=1"
    )


def test_unsupported_media_and_budget_exhaustion_are_typed_without_substitutes(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, handler, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=1)

    result = tools.read_sources(
        entries=[
            {"source": f"{origin}/binary", "focus": "reservation capacity"},
            {"source": f"{origin}/source", "focus": "reservation capacity"},
        ]
    )

    assert result["reads"] == []
    assert [failure["code"] for failure in result["failures"]] == [
        "unsupported_media_type",
        "fetch_budget_exhausted",
    ]
    assert [failure["phase"] for failure in result["failures"]] == ["extract", "fetch"]
    assert all("original_code" in failure["details"] for failure in result["failures"])
    assert not any(urlsplit(request).path == "/source" for request in handler.requests)


def test_unknown_candidate_and_source_handles_fail_closed_without_autocorrection(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, handler, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=1)

    result = tools.read_sources(
        entries=[
            {"source": "C99", "focus": "reservation capacity"},
            {"source": "S99", "focus": "reservation capacity"},
        ]
    )

    assert result["reads"] == []
    assert [item["code"] for item in result["failures"]] == [
        "unknown_candidate_handle",
        "unknown_source_handle",
    ]
    assert [item["details"]["original_message"] for item in result["failures"]] == [
        "C99",
        "S99",
    ]
    assert handler.requests == []


def test_failed_oversized_read_still_charges_the_total_byte_ceiling(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    tools = make_tools(
        tmp_path / "evidence",
        origin,
        client,
        max_fetches=2,
        max_total_bytes=32,
    )

    result = tools.read_sources(
        entries=[{"source": f"{origin}/source", "focus": "reservation capacity"}]
    )

    assert result["reads"] == []
    assert result["failures"][0]["code"] == "total_byte_budget_exhausted"
    assert result["remaining_budget"]["bytes"] == 0


def test_retained_byte_tampering_is_detected_before_extract(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=1)
    result = tools.read_sources(
        entries=[{"source": f"{origin}/source", "focus": "reservation capacity"}]
    )
    source_handle = result["reads"][0]["source_handle"]
    revision_id = tools.store.resolve_source_handle(source_handle)
    body_path = tools.store.revision_body_path(revision_id)
    body_path.chmod(0o600)
    body_path.write_bytes(b"tampered")

    reread = tools.read_sources(
        entries=[{"source": source_handle, "focus": "reservation capacity"}]
    )

    assert reread["reads"] == []
    assert reread["failures"][0]["phase"] == "evidence"
    assert reread["failures"][0]["code"] == "source_revision_digest_mismatch"
    assert "body digest" in reread["failures"][0]["message"]


def test_read_sources_accepts_agent_authored_focused_entries_per_source(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    store = EvidenceStore(tmp_path / "evidence")
    tools = ResearchTools(
        store=store,
        config=ResearchConfig(searxng_url=origin, request_timeout_seconds=2.0),
        budget=ResearchBudget(max_fetches=2),
        http_client=client,
    )

    result = tools.read_sources(
        entries=[
            {"source": f"{origin}/focused", "focus": "issuance deadline"},
            {"source": f"{origin}/focused", "focus": "when payment becomes due"},
        ]
    )

    assert result["failures"] == []
    issuance, payment = result["reads"]
    assert issuance["focus"] == "issuance deadline"
    assert payment["focus"] == "when payment becomes due"
    assert all("issuance deadline" in item["text"] for item in issuance["passages"])
    assert [item["text"] for item in payment["passages"]] == [
        "Payment becomes due only on the separately agreed payment date."
    ]
    handles = [item["evidence_handle"] for item in issuance["passages"] + payment["passages"]]
    assert len(handles) == len(set(handles))
    serialized = json.dumps(result, sort_keys=True)
    assert RAW_HEX_ID.search(serialized) is None
    assert "passage_id" not in serialized
    assert "extraction" not in serialized
    for read in (issuance, payment):
        revision_id = store.resolve_source_handle(read["source_handle"])
        for passage in read["passages"]:
            evidence_revision_id, passage_id = store.resolve_evidence_handle(
                passage["evidence_handle"]
            )
            assert evidence_revision_id == revision_id
            assert passage_id.startswith("passage-")
        assert store.read_revision(revision_id).body == FOCUSED_PAGE_BYTES


def test_read_sources_rejects_invalid_or_empty_entries_without_fetching(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, handler, client = research_origin
    tools = make_tools(tmp_path / "evidence", origin, client, max_fetches=1)

    empty = tools.read_sources(entries=[])
    assert empty["reads"] == []
    assert empty["failures"][0]["code"] == "invalid_read_entries"
    assert empty["failures"][0]["details"]["original_code"] == "invalid_arguments"

    invalid = tools.read_sources(
        entries=[
            {"source": "", "focus": "reservation capacity"},
            {"source": f"{origin}/source", "focus": "  "},
            {"source": "source-revision-" + "a" * 64, "focus": "reservation capacity"},
        ]
    )

    assert invalid["reads"] == []
    assert [item["code"] for item in invalid["failures"]] == [
        "invalid_read_entry",
        "invalid_read_entry",
        "protected_source_id_not_allowed",
    ]
    assert [item["details"]["entry_index"] for item in invalid["failures"]] == [0, 1, 2]
    assert handler.requests == []


def test_focused_read_filters_page_chrome_bounds_exact_passages_and_reports_no_match(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    store = EvidenceStore(tmp_path / "evidence")
    tools = ResearchTools(
        store=store,
        config=ResearchConfig(
            searxng_url=origin,
            request_timeout_seconds=2.0,
            max_passages_per_read=2,
        ),
        budget=ResearchBudget(max_fetches=1),
        http_client=client,
    )

    focused = tools.read_sources(
        entries=[{"source": f"{origin}/focused", "focus": "issuance deadline"}]
    )["reads"][0]

    assert focused["focus_result"] == {
        "status": "matched",
        "matched_passage_count": 3,
        "returned_passage_count": 2,
        "truncated": True,
    }
    assert [item["text"] for item in focused["passages"]] == [
        "The invoice issuance deadline is no later than 30 days after delivery.",
        "The issuance deadline is measured from the delivery date.",
    ]
    serialized = json.dumps(focused, sort_keys=True)
    for excluded in ("header", "navigation", "sidebar", "footer", "noscript", "const"):
        assert excluded not in serialized
    retained = store.read_revision(store.resolve_source_handle(focused["source_handle"]))
    assert retained.body == FOCUSED_PAGE_BYTES

    no_match = tools.read_sources(
        entries=[
            {"source": focused["source_handle"], "focus": "warehouse inventory reconciliation"}
        ]
    )["reads"][0]
    assert no_match["focus_result"] == {
        "status": "no_match",
        "matched_passage_count": 0,
        "returned_passage_count": 0,
        "truncated": False,
    }
    assert no_match["passages"] == []


def test_visible_evidence_run_cap_allows_existing_handles_but_blocks_new_passages(
    tmp_path: Path,
    research_origin: tuple[str, _ResearchOrigin, httpx.Client],
) -> None:
    origin, _, client = research_origin
    store = EvidenceStore(tmp_path / "evidence")
    tools = ResearchTools(
        store=store,
        config=ResearchConfig(
            searxng_url=origin,
            request_timeout_seconds=2.0,
            max_passages_per_read=3,
            max_visible_passages_per_run=2,
        ),
        budget=ResearchBudget(max_fetches=1),
        http_client=client,
    )

    first = tools.read_sources(
        entries=[{"source": f"{origin}/focused", "focus": "issuance deadline"}]
    )["reads"][0]
    source_handle = first["source_handle"]
    repeated = tools.read_sources(
        entries=[{"source": source_handle, "focus": "issuance deadline"}]
    )["reads"][0]
    new_focus = tools.read_sources(
        entries=[{"source": source_handle, "focus": "payment becomes due"}]
    )["reads"][0]

    assert [item["evidence_handle"] for item in first["passages"]] == ["E1", "E2"]
    assert [item["evidence_handle"] for item in repeated["passages"]] == ["E1", "E2"]
    assert repeated["focus_result"]["truncated"] is True
    assert new_focus["passages"] == []
    assert new_focus["focus_result"] == {
        "status": "run_limit_reached",
        "matched_passage_count": 1,
        "returned_passage_count": 0,
        "truncated": True,
    }
    assert store.evidence_handles() == ("E1", "E2")

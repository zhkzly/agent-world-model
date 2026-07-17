"""Internal research values.

These values are deliberately not Environment evidence contracts.  Designer
must materialize the raw and extracted bytes in the ArtifactStore before it
may create an ``Evidence`` node.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


class ResearchEvidenceUnavailable(RuntimeError):
    """A completed research attempt produced no admissible fetched body.

    Only closed classification and observed call counts cross the Research
    boundary.  Raw queries, URLs, and provider messages deliberately do not.
    """

    def __init__(
        self,
        *,
        reason: ResearchEvidenceUnavailableReason,
        search_calls: int,
        fetch_calls: int,
        summary: str,
    ) -> None:
        super().__init__(summary)
        self.reason = reason
        self.search_calls = search_calls
        self.fetch_calls = fetch_calls
        self.failure_code = (
            "research_infrastructure_upstream_unavailable"
            if reason == "upstream_unavailable"
            else f"research_{reason}"
        )


type ResearchEvidenceUnavailableReason = Literal[
    "true_empty",
    "degraded_empty",
    "upstream_unavailable",
    "fetch_attrition",
    "budget_exhausted",
    "mixed",
]


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    language: str = "all"
    categories: tuple[str, ...] = ("general",)
    time_range: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("search query cannot be empty")


@dataclass(frozen=True, slots=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    engine: str | None = None
    score: float | None = None
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class SearchUpstreamFailure:
    engine: str
    reason: str

    def __post_init__(self) -> None:
        if not self.engine or not self.reason:
            raise ValueError("search upstream failure requires engine and reason")


@dataclass(frozen=True, slots=True)
class SearchRecord:
    query: SearchQuery
    provider: str
    requested_at: datetime
    raw_response_sha256: str
    hits: tuple[SearchHit, ...]
    upstream_failures: tuple[SearchUpstreamFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    fetched_at: datetime
    status_code: int
    media_type: str
    body: bytes = field(repr=False)
    response_headers: tuple[tuple[str, str], ...] = ()
    fetcher: str = "http"
    network_assurance: str = "unrecorded"
    resolved_addresses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    source: FetchedDocument
    text: str
    title: str | None
    raw_sha256: str
    text_sha256: str
    extractor: str
    extractor_version: str


@dataclass(frozen=True, slots=True)
class FetchFailure:
    stage: str
    error_type: str
    identity_sha256: str
    message_sha256: str

    @classmethod
    def redacted(
        cls,
        *,
        stage: str,
        error_type: str,
        identity: str,
        message: str,
    ) -> FetchFailure:
        """Create a cross-component failure without retaining sensitive text."""

        return cls(
            stage=stage,
            error_type=error_type,
            identity_sha256="sha256:"
            + hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest(),
            message_sha256="sha256:"
            + hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ResearchBundle:
    searches: tuple[SearchRecord, ...]
    documents: tuple[ExtractedDocument, ...]
    failures: tuple[FetchFailure, ...]
    search_calls: int
    fetch_calls: int

    def evidence_unavailable_summary(self) -> str:
        """Return one credential/URL-free stage aggregate for failed admission."""

        hit_count = sum(len(search.hits) for search in self.searches)
        upstream_count = sum(len(search.upstream_failures) for search in self.searches)
        failure_counts = Counter((failure.stage, failure.error_type) for failure in self.failures)
        failure_summary = ",".join(
            f"{stage}/{error_type}={count}"
            for (stage, error_type), count in sorted(failure_counts.items())
        )
        return (
            "research evidence unavailable: "
            f"hits={hit_count}, fetch_calls={self.fetch_calls}, "
            f"upstream_failures={upstream_count}, admitted_documents={len(self.documents)}, "
            f"failures={failure_summary or 'none'}"
        )

    def evidence_unavailable_reason(self) -> ResearchEvidenceUnavailableReason:
        """Classify admission failure without inspecting raw provider text."""

        hit_count = sum(len(search.hits) for search in self.searches)
        upstream_count = sum(len(search.upstream_failures) for search in self.searches)
        if any(failure.error_type == "ResearchBudgetExceeded" for failure in self.failures):
            return "budget_exhausted"
        search_failures = tuple(failure for failure in self.failures if failure.stage == "search")
        if self.search_calls and not self.searches and len(search_failures) >= self.search_calls:
            return "upstream_unavailable"
        if hit_count == 0 and not self.failures:
            return "degraded_empty" if upstream_count else "true_empty"
        if hit_count or self.fetch_calls or any(
            failure.stage in {"fetch", "extract", "safety"} for failure in self.failures
        ):
            return "fetch_attrition"
        if hit_count == 0 and (upstream_count or search_failures):
            return "degraded_empty"
        return "mixed"

    def require_evidence(self) -> ResearchBundle:
        """Fail closed when no source body was actually fetched and extracted."""

        if not self.documents:
            raise ResearchEvidenceUnavailable(
                reason=self.evidence_unavailable_reason(),
                search_calls=self.search_calls,
                fetch_calls=self.fetch_calls,
                summary=self.evidence_unavailable_summary(),
            )
        return self


JsonObject = dict[str, Any]


__all__ = [
    "ExtractedDocument",
    "FetchFailure",
    "FetchedDocument",
    "JsonObject",
    "ResearchBundle",
    "ResearchEvidenceUnavailable",
    "ResearchEvidenceUnavailableReason",
    "SearchHit",
    "SearchQuery",
    "SearchRecord",
    "SearchUpstreamFailure",
]

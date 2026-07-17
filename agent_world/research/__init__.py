"""Real research toolchain used by Designer and Discovery.

Search snippets are candidates only.  A source becomes evidence only after a
fetcher retrieves bytes and an extractor produces non-empty content with
provenance and hashes.
"""

from .factory import build_research_toolchain
from .models import (
    ExtractedDocument,
    FetchedDocument,
    FetchFailure,
    ResearchBundle,
    ResearchEvidenceUnavailable,
    ResearchEvidenceUnavailableReason,
    SearchHit,
    SearchQuery,
    SearchRecord,
    SearchUpstreamFailure,
)
from .passages import build_evidence_passage_pack
from .providers import (
    HttpFetcher,
    JinaReaderFetcher,
    JinaSearchProvider,
    ResearchPermissionError,
    ResearchProviderError,
    SearchUpstreamUnavailable,
    SearxngSearchProvider,
    TrafilaturaExtractor,
    UrlPolicy,
)
from .security import ResearchSafetyError
from .service import ResearchAccessPolicy, ResearchToolchain

__all__ = [
    "ExtractedDocument",
    "FetchFailure",
    "FetchedDocument",
    "HttpFetcher",
    "JinaReaderFetcher",
    "JinaSearchProvider",
    "ResearchAccessPolicy",
    "ResearchBundle",
    "ResearchEvidenceUnavailable",
    "ResearchEvidenceUnavailableReason",
    "ResearchPermissionError",
    "ResearchProviderError",
    "ResearchSafetyError",
    "ResearchToolchain",
    "SearchHit",
    "SearchQuery",
    "SearchRecord",
    "SearchUpstreamFailure",
    "SearxngSearchProvider",
    "SearchUpstreamUnavailable",
    "TrafilaturaExtractor",
    "UrlPolicy",
    "build_research_toolchain",
    "build_evidence_passage_pack",
]

"""Research orchestration with explicit permissions and failure accounting."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from agent_world.control.telemetry import TelemetryStore, WorkSpan

from agent_world.contracts import ArtifactRef, PermissionScope

from .models import (
    ExtractedDocument,
    FetchedDocument,
    FetchFailure,
    ResearchBundle,
    SearchQuery,
    SearchRecord,
)
from .providers import (
    ResearchPermissionError,
    ResearchProviderError,
    UrlPolicy,
)
from .security import (
    MAX_RESEARCH_EXTRACTED_BYTES,
    MAX_RESEARCH_RAW_BYTES,
    ResearchSafetyError,
    assert_safe_research_document,
)

_SEARCH_CAPABILITY = "research.search"
_FETCH_CAPABILITY = "research.fetch"
_READER_CAPABILITY = "research.reader"


class SearchProvider(Protocol):
    name: str

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord: ...


class Fetcher(Protocol):
    name: str

    async def fetch(
        self,
        url: str,
        *,
        source_policy: UrlPolicy | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument: ...


class Extractor(Protocol):
    name: str

    async def extract(self, source: FetchedDocument) -> ExtractedDocument: ...


@dataclass(frozen=True, slots=True)
class ResearchAccessPolicy:
    """Effective least-privilege view of request and current-run permissions."""

    request_permissions: PermissionScope
    run_permissions: PermissionScope
    allowed_source_kinds: frozenset[str]
    source_policy: UrlPolicy
    credential_handles: frozenset[str]

    @classmethod
    def create(
        cls,
        *,
        request_permissions: PermissionScope,
        run_permissions: PermissionScope,
        allowed_source_kinds: Sequence[str],
        allow_rfc2544_synthetic_egress: bool = False,
    ) -> ResearchAccessPolicy:
        source_kinds = frozenset(allowed_source_kinds)
        if source_kinds != {"web"}:
            raise ResearchPermissionError(
                "the current research toolchain implements exactly the web source kind"
            )
        source_policy = UrlPolicy(
            allowed_domains=request_permissions.network_domains,
            additional_allowed_domain_sets=(run_permissions.network_domains,),
            allow_rfc2544_synthetic_egress=allow_rfc2544_synthetic_egress,
        )
        # Empty network domain sets intentionally mean any public Web origin.  UrlPolicy still
        # rejects private/reserved addresses and checks every redirect hop.
        credential_handles = frozenset(request_permissions.credential_handles).intersection(
            run_permissions.credential_handles
        )
        access = cls(
            request_permissions=request_permissions,
            run_permissions=run_permissions,
            allowed_source_kinds=source_kinds,
            source_policy=source_policy,
            credential_handles=credential_handles,
        )
        access.require_capability(_SEARCH_CAPABILITY)
        access.require_capability(_FETCH_CAPABILITY)
        return access

    def require_capability(self, capability: str) -> None:
        for label, scope in (
            ("request", self.request_permissions),
            ("run", self.run_permissions),
        ):
            if scope.tool_allowlist and capability not in scope.tool_allowlist:
                raise ResearchPermissionError(
                    f"{label} permissions do not authorize research capability {capability}"
                )


class ResearchToolchain:
    """Execute bounded real searches and fetch bodies before admitting evidence."""

    def __init__(
        self,
        search_provider: SearchProvider,
        primary_fetcher: Fetcher,
        extractor: Extractor,
        *,
        fallback_fetcher: Fetcher | None = None,
        max_parallel_searches: int = 4,
        max_parallel_fetches: int = 4,
        allow_rfc2544_synthetic_egress: bool = False,
        telemetry: TelemetryStore | None = None,
    ) -> None:
        if max_parallel_searches < 1 or max_parallel_fetches < 1:
            raise ValueError("research parallelism must be positive")
        self.search_provider = search_provider
        self.primary_fetcher = primary_fetcher
        self.fallback_fetcher = fallback_fetcher
        self.extractor = extractor
        self.max_parallel_searches = max_parallel_searches
        self.max_parallel_fetches = max_parallel_fetches
        self.allow_rfc2544_synthetic_egress = allow_rfc2544_synthetic_egress
        self.telemetry = telemetry

    async def run(
        self,
        queries: Sequence[SearchQuery],
        *,
        request_permissions: PermissionScope,
        run_permissions: PermissionScope,
        allowed_source_kinds: Sequence[str],
        maximum_tool_calls: int,
        results_per_query: int = 8,
        max_documents: int = 12,
        seed_urls: Sequence[str] = (),
        require_evidence: bool = True,
    ) -> ResearchBundle:
        if not queries:
            raise ValueError("research requires at least one query")
        minimum_required_calls = len(queries) + 2
        if self.fallback_fetcher is not None:
            # A configured fallback is an actual potential network tool call.
            # Reserve it up front so a primary failure cannot leave a fetched
            # but unextractable body or silently escape the Work budget.
            minimum_required_calls += 1
        if maximum_tool_calls < minimum_required_calls:
            raise ValueError(
                "research maximum_tool_calls must reserve every search, fetch, and extract"
            )
        access = ResearchAccessPolicy.create(
            request_permissions=request_permissions,
            run_permissions=run_permissions,
            allowed_source_kinds=allowed_source_kinds,
            allow_rfc2544_synthetic_egress=self.allow_rfc2544_synthetic_egress,
        )
        if self.fallback_fetcher is not None:
            access.require_capability(_READER_CAPABILITY)
        known_secret_values = self._sensitive_values(access.credential_handles)
        search_records: list[SearchRecord] = []
        failures: list[FetchFailure] = []
        tool_calls_used = 0
        search_calls_used = 0
        fetch_calls_used = 0
        extract_calls_used = 0
        tool_call_lock = asyncio.Lock()

        async def authorize_tool_call(kind: Literal["search", "fetch", "extract"]) -> bool:
            nonlocal tool_calls_used, search_calls_used, fetch_calls_used, extract_calls_used
            async with tool_call_lock:
                if tool_calls_used >= maximum_tool_calls:
                    return False
                tool_calls_used += 1
                if kind == "search":
                    search_calls_used += 1
                elif kind == "fetch":
                    fetch_calls_used += 1
                else:
                    extract_calls_used += 1
                return True

        search_semaphore = asyncio.Semaphore(self.max_parallel_searches)

        async def execute_search(
            query: SearchQuery,
        ) -> SearchRecord | FetchFailure | ResearchPermissionError:
            async with search_semaphore:
                if not await authorize_tool_call("search"):
                    return FetchFailure.redacted(
                        stage="search",
                        error_type="ResearchBudgetExceeded",
                        identity=query.text,
                        message="search was blocked by maximum_tool_calls",
                    )
                span = self._start_operation_span(
                    operation="research.search",
                    provider=self.search_provider.name,
                    identity=query.text,
                )
                try:
                    record = await self.search_provider.search(
                        query,
                        limit=results_per_query,
                        credential_handles=access.credential_handles,
                    )
                    self._finish_operation_span(span, status="passed")
                    return record
                except ResearchPermissionError as exc:
                    self._finish_operation_span(
                        span,
                        status="needs_human",
                        error_code=type(exc).__name__,
                    )
                    return exc
                except Exception as exc:  # provider failures are typed into the run record
                    self._finish_operation_span(
                        span,
                        status="failed",
                        error_code=type(exc).__name__,
                    )
                    return FetchFailure.redacted(
                        stage="search",
                        error_type=type(exc).__name__,
                        identity=query.text,
                        message=str(exc),
                    )

        search_results = await asyncio.gather(*(execute_search(query) for query in queries))
        permission_failures = [
            item for item in search_results if isinstance(item, ResearchPermissionError)
        ]
        if permission_failures:
            raise permission_failures[0]
        for item in search_results:
            if isinstance(item, SearchRecord):
                search_records.append(item)
            else:
                assert isinstance(item, FetchFailure)
                failures.append(item)

        urls: list[str] = []
        seen: set[str] = set()
        for url in seed_urls:
            normalized = url.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)
            if len(urls) >= max_documents:
                break
        for record in search_records:
            for hit in record.hits:
                if hit.url not in seen:
                    seen.add(hit.url)
                    urls.append(hit.url)
                if len(urls) >= max_documents:
                    break
            if len(urls) >= max_documents:
                break

        remaining_for_documents = maximum_tool_calls - tool_calls_used
        # A document is evidence only after both fetching and extraction.  When
        # a fallback fetcher is configured, reserve that additional network
        # operation for every selected URL; unused fallback capacity remains
        # visible as unused reservation instead of becoming unbudgeted work.
        calls_per_document = 3 if self.fallback_fetcher is not None else 2
        maximum_primary_urls = remaining_for_documents // calls_per_document
        urls = urls[:maximum_primary_urls]

        semaphore = asyncio.Semaphore(self.max_parallel_fetches)

        async def fetch_and_extract(
            url: str,
        ) -> tuple[ExtractedDocument | None, FetchFailure | None]:
            async with semaphore:
                if not await authorize_tool_call("fetch"):
                    return None, FetchFailure.redacted(
                        stage="fetch",
                        error_type="ResearchBudgetExceeded",
                        identity=url,
                        message="primary fetch was blocked by maximum_tool_calls",
                    )
                primary_span = self._start_operation_span(
                    operation="research.fetch",
                    provider=self.primary_fetcher.name,
                    identity=url,
                )
                try:
                    source = await self.primary_fetcher.fetch(
                        url,
                        source_policy=access.source_policy,
                        credential_handles=access.credential_handles,
                    )
                    self._finish_operation_span(primary_span, status="passed")
                except ResearchPermissionError as exc:
                    self._finish_operation_span(
                        primary_span,
                        status="needs_human",
                        error_code=type(exc).__name__,
                    )
                    raise
                except Exception as primary_exc:
                    self._finish_operation_span(
                        primary_span,
                        status="failed",
                        error_code=type(primary_exc).__name__,
                    )
                    if self.fallback_fetcher is None:
                        return None, FetchFailure.redacted(
                            stage="fetch",
                            error_type=type(primary_exc).__name__,
                            identity=url,
                            message=str(primary_exc),
                        )
                    fallback_span: WorkSpan | None = None
                    try:
                        if not await authorize_tool_call("fetch"):
                            return None, FetchFailure.redacted(
                                stage="fetch",
                                error_type="ResearchBudgetExceeded",
                                identity=url,
                                message=(
                                    "primary fetch failed and Reader fallback was blocked by "
                                    "maximum_tool_calls"
                                ),
                            )
                        fallback_span = self._start_operation_span(
                            operation="research.fetch",
                            provider=self.fallback_fetcher.name,
                            identity=url,
                        )
                        source = await self.fallback_fetcher.fetch(
                            url,
                            source_policy=access.source_policy,
                            credential_handles=access.credential_handles,
                        )
                        self._finish_operation_span(fallback_span, status="passed")
                    except ResearchPermissionError as exc:
                        self._finish_operation_span(
                            fallback_span,
                            status="needs_human",
                            error_code=type(exc).__name__,
                        )
                        raise
                    except Exception as fallback_exc:
                        self._finish_operation_span(
                            fallback_span,
                            status="failed",
                            error_code=type(fallback_exc).__name__,
                        )
                        return None, FetchFailure.redacted(
                            stage="fetch",
                            error_type=type(fallback_exc).__name__,
                            identity=url,
                            message=f"primary={primary_exc}; fallback={fallback_exc}",
                        )
                if not await authorize_tool_call("extract"):
                    return None, FetchFailure.redacted(
                        stage="extract",
                        error_type="ResearchBudgetExceeded",
                        identity=url,
                        message="extract was blocked by maximum_tool_calls",
                    )
                extract_span = self._start_operation_span(
                    operation="research.extract",
                    provider=self.extractor.name,
                    identity=source.final_url,
                )
                try:
                    document = await self.extractor.extract(source)
                    assert_safe_research_document(
                        document,
                        known_secret_values=known_secret_values,
                    )
                    self._finish_operation_span(extract_span, status="passed")
                    return document, None
                except (
                    ResearchProviderError,
                    ResearchSafetyError,
                    UnicodeError,
                    ValueError,
                ) as exc:
                    self._finish_operation_span(
                        extract_span,
                        status="failed",
                        error_code=type(exc).__name__,
                    )
                    return None, FetchFailure.redacted(
                        stage="safety" if isinstance(exc, ResearchSafetyError) else "extract",
                        error_type=type(exc).__name__,
                        identity=url,
                        message=str(exc),
                    )

        results = await asyncio.gather(*(fetch_and_extract(url) for url in urls))
        documents: list[ExtractedDocument] = []
        total_raw = 0
        total_extracted = 0
        for document, failure in results:
            if document is not None:
                raw_size = len(document.source.body)
                extracted_size = len(document.text.encode("utf-8"))
                if (
                    total_raw + raw_size > MAX_RESEARCH_RAW_BYTES
                    or total_extracted + extracted_size > MAX_RESEARCH_EXTRACTED_BYTES
                ):
                    failures.append(
                        FetchFailure.redacted(
                            stage="safety",
                            error_type="ResearchSafetyError",
                            identity=document.source.final_url,
                            message="research run exceeded fixed aggregate source-body limits",
                        )
                    )
                else:
                    total_raw += raw_size
                    total_extracted += extracted_size
                    documents.append(document)
            if failure is not None:
                failures.append(failure)
        bundle = ResearchBundle(
            searches=tuple(search_records),
            documents=tuple(documents),
            failures=tuple(failures),
            search_calls=search_calls_used,
            fetch_calls=fetch_calls_used,
            extract_calls=extract_calls_used,
        )
        if self.telemetry is not None:
            current = self.telemetry.current_trace()
            if current is not None:
                self.telemetry.record_research_bundle(
                    trace_id=current[0],
                    # Record actual calls and attrition even when evidence
                    # admission below fails. Failed work is still real work.
                    bundle=bundle,
                    span_id=current[3],
                )
        result = bundle.require_evidence() if require_evidence else bundle
        return result

    def _start_operation_span(
        self,
        *,
        operation: str,
        provider: str,
        identity: str,
    ) -> WorkSpan | None:
        """Expose each real tool operation without persisting query or URL text."""

        if self.telemetry is None:
            return None
        current = self.telemetry.current_trace()
        if current is None:
            return None
        span = self.telemetry.start_span(
            trace_id=current[0],
            component="research",
            operation=operation,
            parent_span_id=current[3],
            run_id=current[1],
            campaign_id=current[2],
            node="research",
            attributes={
                "provider": provider,
                "identity_hash": "sha256:"
                + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            },
        )
        # Search/fetch can be the longest non-Agent operations. Make admission
        # visible to a concurrent inspector rather than waiting for batch commit.
        self.telemetry.flush()
        return span

    def record_checkpoint_reuse(
        self,
        *,
        checkpoint_ref: ArtifactRef,
        evidence_graph_ref: ArtifactRef,
    ) -> None:
        """Record honest evidence reuse without pretending external tools ran again."""

        if self.telemetry is None:
            return
        current = self.telemetry.current_trace()
        if current is None:
            return
        from agent_world.control.telemetry import MetricPoint

        span = self.telemetry.start_span(
            trace_id=current[0],
            component="research",
            operation="research.checkpoint_reuse",
            parent_span_id=current[3],
            run_id=current[1],
            campaign_id=current[2],
            node="research",
            input_refs=(checkpoint_ref, evidence_graph_ref),
            attributes={
                "checkpoint_revision_hash": checkpoint_ref.revision_id,
                "evidence_revision_hash": evidence_graph_ref.revision_id,
            },
        )
        self.telemetry.flush()
        span.finish(
            status="passed",
            output_refs=(evidence_graph_ref,),
            metrics=(
                MetricPoint("research.search.calls", None, "calls", "unknown"),
                MetricPoint("research.fetch.calls", None, "calls", "unknown"),
                MetricPoint("research.extract.calls", None, "calls", "unknown"),
                MetricPoint(
                    "research.documents.extracted",
                    None,
                    "documents",
                    "unknown",
                ),
                MetricPoint("research.checkpoint.reused", 1, "checkpoints", "framework"),
            ),
        )
        self.telemetry.flush()

    def _finish_operation_span(
        self,
        span: WorkSpan | None,
        *,
        status: Literal["passed", "failed", "needs_human"],
        error_code: str | None = None,
    ) -> None:
        if span is None:
            return
        span.finish(status=status, error_code=error_code)
        if self.telemetry is None:  # defensive invariant for static and runtime safety
            raise RuntimeError("research span exists without a TelemetryStore")
        self.telemetry.flush()

    def _sensitive_values(self, credential_handles: frozenset[str]) -> tuple[str, ...]:
        values: list[str] = []
        for provider in (self.search_provider, self.fallback_fetcher):
            if provider is None:
                continue
            resolver = getattr(provider, "sensitive_values", None)
            if resolver is None:
                continue
            for value in resolver(credential_handles):
                if value and value not in values:
                    values.append(value)
        return tuple(values)


__all__ = ["ResearchAccessPolicy", "ResearchToolchain"]

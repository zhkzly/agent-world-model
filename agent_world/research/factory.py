"""Construct the configured real search/fetch/extract toolchain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_world.control.telemetry import TelemetryStore

from agent_world.config import ResearchConfig

from .providers import (
    HttpFetcher,
    JinaReaderFetcher,
    JinaSearchProvider,
    SearxngSearchProvider,
    TrafilaturaExtractor,
    UrlPolicy,
)
from .service import ResearchToolchain, SearchProvider


def build_research_toolchain(
    config: ResearchConfig,
    *,
    source_environment: Mapping[str, str] | None = None,
    telemetry: TelemetryStore | None = None,
) -> ResearchToolchain:
    source_policy = UrlPolicy(
        allow_rfc2544_synthetic_egress=config.allow_rfc2544_synthetic_egress,
    )
    search: SearchProvider
    if config.provider == "searxng":
        assert config.searxng_base_url is not None
        search = SearxngSearchProvider(
            str(config.searxng_base_url),
            timeout_seconds=config.request_timeout_seconds,
            allow_private_endpoint=config.searxng_allow_private_endpoint,
        )
    else:
        assert config.jina_api_key_environment is not None
        search = JinaSearchProvider(
            endpoint=str(config.jina_search_url),
            api_key_env=config.jina_api_key_environment,
            credential_handle=config.jina_credential_handle,
            timeout_seconds=config.request_timeout_seconds,
            source_environment=source_environment,
            allow_rfc2544_synthetic_egress=config.allow_rfc2544_synthetic_egress,
        )
    primary = HttpFetcher(
        source_policy,
        timeout_seconds=config.request_timeout_seconds,
        max_bytes=config.max_response_bytes,
    )
    fallback = (
        JinaReaderFetcher(
            source_policy,
            base_url=str(config.jina_reader_url),
            api_key_env=config.jina_api_key_environment,
            credential_handle=config.jina_credential_handle,
            timeout_seconds=config.request_timeout_seconds,
            max_bytes=config.max_response_bytes,
            source_environment=source_environment,
            allow_rfc2544_synthetic_egress=config.allow_rfc2544_synthetic_egress,
        )
        if config.use_jina_reader_fallback
        else None
    )
    return ResearchToolchain(
        search_provider=search,
        primary_fetcher=primary,
        fallback_fetcher=fallback,
        extractor=TrafilaturaExtractor(timeout_seconds=config.request_timeout_seconds),
        max_parallel_searches=config.max_parallel_searches,
        max_parallel_fetches=config.max_parallel_fetches,
        allow_rfc2544_synthetic_egress=config.allow_rfc2544_synthetic_egress,
        telemetry=telemetry,
    )


__all__ = ["build_research_toolchain"]

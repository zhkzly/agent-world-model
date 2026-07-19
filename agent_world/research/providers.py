"""Concrete network providers with provenance and SSRF controls."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.metadata
import ipaddress
import json
import os
import re
import socket
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Any
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

import httpx
from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

from .models import (
    ExtractedDocument,
    FetchedDocument,
    SearchHit,
    SearchQuery,
    SearchRecord,
    SearchUpstreamFailure,
)
from .security import (
    MAX_RAW_DOCUMENT_BYTES,
    ResearchSafetyError,
    assert_secret_free,
    normalize_research_text,
    sensitive_url_parameter,
)


class ResearchProviderError(RuntimeError):
    """A real provider failed; callers must not reinterpret this as evidence."""


class ResearchPermissionError(ResearchProviderError):
    """A configured provider capability was not authorized for this run."""


class SearchUpstreamUnavailable(ResearchProviderError):
    """Search completed at the adapter but every useful upstream engine failed."""


_MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
_RFC2544_SYNTHETIC_EGRESS = ipaddress.ip_network("198.18.0.0/15")


def _searxng_upstream_failures(value: Any) -> tuple[SearchUpstreamFailure, ...]:
    """Parse a bounded safe projection of SearXNG engine attrition."""

    if not isinstance(value, list):
        return ()
    failures: list[SearchUpstreamFailure] = []
    for item in value[:64]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        engine = normalize_research_text(str(item[0]))[:80]
        reason = normalize_research_text(str(item[1]))[:160]
        if engine and reason:
            failures.append(SearchUpstreamFailure(engine=engine, reason=reason))
    return tuple(failures)


@dataclass(frozen=True, slots=True)
class UrlResolution:
    url: str
    host: str
    port: int
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
    permits_private: bool = False
    uses_synthetic_egress: bool = False


class UrlPolicy:
    """Validate public HTTP(S) sources and explicit private service exceptions."""

    def __init__(
        self,
        *,
        allowed_domains: Iterable[str] = (),
        additional_allowed_domain_sets: Iterable[Iterable[str]] = (),
        private_host_exceptions: Iterable[str] = (),
        allow_rfc2544_synthetic_egress: bool = False,
        dns_timeout_seconds: float = 10.0,
    ) -> None:
        if dns_timeout_seconds <= 0:
            raise ValueError("DNS timeout must be positive")
        domain_sets = (
            tuple(allowed_domains),
            *tuple(tuple(items) for items in additional_allowed_domain_sets),
        )
        self._allowed_domain_sets = tuple(
            tuple(self._normalize_domain_pattern(item) for item in items) for items in domain_sets
        )
        self._private_exceptions = frozenset(
            self._normalize_host(item) for item in private_host_exceptions
        )
        self._allow_rfc2544_synthetic_egress = allow_rfc2544_synthetic_egress
        self._dns_timeout_seconds = dns_timeout_seconds

    @staticmethod
    def _normalize_host(value: str) -> str:
        return value.rstrip(".").encode("idna").decode("ascii").lower()

    @classmethod
    def _normalize_domain_pattern(cls, value: str) -> str:
        lowered = value.strip().rstrip(".").lower()
        prefix = ""
        if lowered.startswith("**."):
            prefix, lowered = "**.", lowered[3:]
        elif lowered.startswith("*."):
            prefix, lowered = "*.", lowered[2:]
        if not lowered or any(character in lowered for character in "/:@?#"):
            raise ValueError(f"invalid network domain pattern: {value!r}")
        return prefix + cls._normalize_host(lowered)

    @staticmethod
    def _matches(host: str, pattern: str) -> bool:
        if pattern.startswith("**."):
            suffix = pattern[3:]
            return host == suffix or host.endswith(f".{suffix}")
        return fnmatch(host, pattern)

    async def resolve(self, url: str) -> UrlResolution:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ResearchProviderError("only absolute http(s) URLs are allowed")
        if parsed.username or parsed.password:
            raise ResearchProviderError("URL userinfo is forbidden")
        try:
            assert_secret_free(url.encode("utf-8"), context="source URL")
        except ResearchSafetyError as exc:
            raise ResearchProviderError(str(exc)) from exc
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise ResearchProviderError("URL has an invalid port") from exc
        host = self._normalize_host(parsed.hostname)
        for patterns in self._allowed_domain_sets:
            # An empty network domain set deliberately means any public Web origin.
            if patterns and not any(self._matches(host, pattern) for pattern in patterns):
                raise ResearchProviderError(f"source domain is outside the allowlist: {host}")
        for name, value in parse_qsl(parsed.query, keep_blank_values=True):
            if sensitive_url_parameter(name):
                raise ResearchProviderError(
                    f"source URL contains a credential-bearing query parameter: {name}"
                )
            if value.lower().startswith(("sk-", "bearer ", "jina_")):
                raise ResearchProviderError("source URL contains credential-like query material")

        permits_private = host in self._private_exceptions

        addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
        try:
            literal = ipaddress.ip_address(host)
            addresses = (literal,)
        except ValueError:
            try:
                resolved = await asyncio.wait_for(
                    asyncio.to_thread(
                        socket.getaddrinfo,
                        host,
                        port,
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=self._dns_timeout_seconds,
                )
            except TimeoutError as exc:
                raise ResearchProviderError(f"DNS resolution timed out for {host}") from exc
            except OSError as exc:
                raise ResearchProviderError(f"DNS resolution failed for {host}: {exc}") from exc
            addresses = tuple(
                sorted(
                    {ipaddress.ip_address(item[4][0]) for item in resolved},
                    key=lambda item: (item.version, int(item)),
                )
            )
        if not addresses:
            raise ResearchProviderError(f"DNS returned no addresses for {host}")
        synthetic_addresses = tuple(
            address
            for address in addresses
            if isinstance(address, ipaddress.IPv4Address)
            and address in _RFC2544_SYNTHETIC_EGRESS
        )
        if not permits_private:
            for address in addresses:
                if address.is_global:
                    continue
                if self._allow_rfc2544_synthetic_egress and address in synthetic_addresses:
                    continue
                raise ResearchProviderError(
                    f"private, loopback, link-local, or reserved source address denied: {address}"
                )
        return UrlResolution(
            url=url,
            host=host,
            port=port,
            addresses=addresses,
            permits_private=permits_private,
            uses_synthetic_egress=bool(synthetic_addresses),
        )

    async def validate(self, url: str) -> str:
        await self.resolve(url)
        return url


def _exact_jina_origin(value: str, *, official_host: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ResearchProviderError("Jina credentials require an exact HTTPS origin")
    if parsed.username or parsed.password:
        raise ResearchProviderError("Jina endpoint userinfo is forbidden")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ResearchProviderError("Jina endpoint has an invalid port") from exc
    if port not in {None, 443}:
        raise ResearchProviderError("Jina credentials cannot be sent to a non-443 port")
    host = parsed.hostname.lower()
    if host != official_host:
        raise ResearchProviderError(
            f"Jina credential origin must be exactly https://{official_host}"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ResearchProviderError("Jina endpoint must contain only its exact origin")
    return f"https://{official_host}"


def _peer_address(response: httpx.Response) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    stream: Any = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return None
    server = stream.get_extra_info("server_addr")
    if not isinstance(server, (tuple, list)) or not server:
        return None
    try:
        address = ipaddress.ip_address(str(server[0]).split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            return address.ipv4_mapped
        return address
    except ValueError:
        return None


async def _verify_response_route(
    response: httpx.Response,
    *,
    policy: UrlPolicy,
    before: UrlResolution,
) -> tuple[str, tuple[str, ...]]:
    """Bind the response to its peer when exposed, plus a post-connect DNS check."""

    peer = _peer_address(response)
    if peer is not None:
        peer_is_synthetic = (
            isinstance(peer, ipaddress.IPv4Address)
            and peer in _RFC2544_SYNTHETIC_EGRESS
            and before.uses_synthetic_egress
        )
        if not before.permits_private and not peer.is_global and not peer_is_synthetic:
            raise ResearchProviderError(f"connected peer address is not public: {peer}")
        if peer not in before.addresses:
            raise ResearchProviderError("connected peer was absent from pre-connect DNS results")
    after = await policy.resolve(before.url)
    if set(after.addresses) != set(before.addresses):
        raise ResearchProviderError("DNS answers changed during the request; fetch denied")
    if before.uses_synthetic_egress:
        assurance = (
            "rfc2544-synthetic-egress-peer+dns-stability"
            if peer is not None
            else "rfc2544-synthetic-egress-dns-stability-only"
        )
    else:
        assurance = "peer-address+dns-stability" if peer is not None else "dns-stability-only"
    return assurance, tuple(str(item) for item in after.addresses)


async def _read_response_bytes(response: httpx.Response, *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > maximum:
            raise ResearchProviderError("provider response exceeded its fixed byte limit")
    return bytes(body)


class SearxngSearchProvider:
    """Use a real SearXNG JSON endpoint; snippets remain non-evidence."""

    name = "searxng-json"

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 20,
        allow_private_endpoint: bool = False,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ResearchProviderError("SearXNG endpoint must be an absolute credential-free URL")
        hostname = parsed.hostname
        self._policy = UrlPolicy(
            allowed_domains=(hostname,),
            private_host_exceptions=(hostname,) if allow_private_endpoint else (),
        )
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del credential_handles
        target = f"{self.endpoint}/search"
        resolution = await self._policy.resolve(target)
        params: dict[str, str | int] = {
            "q": query.text,
            "format": "json",
            "language": query.language,
            "categories": ",".join(query.categories),
        }
        if query.time_range is not None:
            params["time_range"] = query.time_range
        requested_at = datetime.now(UTC)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream("GET", target, params=params) as response:
                    await _verify_response_route(
                        response,
                        policy=self._policy,
                        before=resolution,
                    )
                    if response.is_redirect:
                        raise ResearchProviderError("SearXNG endpoint redirects are forbidden")
                    response.raise_for_status()
                    response_content = await _read_response_bytes(
                        response,
                        maximum=_MAX_SEARCH_RESPONSE_BYTES,
                    )
        except httpx.HTTPError as exc:
            raise SearchUpstreamUnavailable("SearXNG transport is unavailable") from exc
        try:
            payload = json.loads(response_content)
            results = payload["results"]
        except (json.JSONDecodeError, KeyError, TypeError, UnicodeError) as exc:
            raise ResearchProviderError("SearXNG did not return its enabled JSON format") from exc
        if not isinstance(payload, dict) or not isinstance(results, list):
            raise ResearchProviderError("SearXNG JSON result list is invalid")
        upstream_failures = _searxng_upstream_failures(payload.get("unresponsive_engines"))
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url or url in seen:
                continue
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            seen.add(url)
            score_value = item.get("score")
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title") or url),
                    snippet=str(item.get("content") or ""),
                    engine=str(item.get("engine")) if item.get("engine") else None,
                    score=float(score_value) if isinstance(score_value, (int, float)) else None,
                    published_at=str(item.get("publishedDate"))
                    if item.get("publishedDate")
                    else None,
                )
            )
            if len(hits) >= limit:
                break
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=requested_at,
            raw_response_sha256=hashlib.sha256(response_content).hexdigest(),
            hits=tuple(hits),
            upstream_failures=upstream_failures,
        )


class BingRssSearchProvider:
    """Use Bing's public RSS search surface with bounded strict XML parsing.

    RSS entries are discovery hints only.  ResearchToolchain still has to
    fetch and extract the selected source body before any claim can cite it.
    """

    name = "bing-rss"

    def __init__(
        self,
        endpoint: str = "https://www.bing.com/search",
        *,
        timeout_seconds: float = 20,
        allow_rfc2544_synthetic_egress: bool = False,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.bing.com"
            or parsed.port is not None
            or parsed.path != "/search"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ResearchProviderError(
                "Bing RSS endpoint must be the exact credential-free HTTPS search origin"
            )
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._policy = UrlPolicy(
            allowed_domains=("www.bing.com",),
            allow_rfc2544_synthetic_egress=allow_rfc2544_synthetic_egress,
            dns_timeout_seconds=min(10.0, timeout_seconds),
        )

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del credential_handles
        requested_at = datetime.now(UTC)
        params: dict[str, str | int] = {
            "q": query.text,
            "format": "rss",
            "count": min(50, max(1, limit)),
        }
        language = query.language.strip().lower()
        if language not in {"", "all", "auto"}:
            if language.startswith("zh"):
                params.update({"setlang": "zh-Hans", "mkt": "zh-CN"})
            elif language.startswith("en"):
                params.update({"setlang": "en", "mkt": "en-US"})
            else:
                params["setlang"] = language
        try:
            async with asyncio.timeout(self.timeout_seconds):
                resolution = await self._policy.resolve(self.endpoint)
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream("GET", self.endpoint, params=params) as response:
                        await _verify_response_route(
                            response,
                            policy=self._policy,
                            before=resolution,
                        )
                        if response.is_redirect:
                            raise ResearchProviderError(
                                "Bing RSS endpoint redirects are forbidden"
                            )
                        response.raise_for_status()
                        response_content = await _read_response_bytes(
                            response,
                            maximum=_MAX_SEARCH_RESPONSE_BYTES,
                        )
        except TimeoutError as exc:
            raise SearchUpstreamUnavailable("Bing RSS request timed out") from exc
        except httpx.HTTPError as exc:
            raise SearchUpstreamUnavailable("Bing RSS transport is unavailable") from exc
        lowered = response_content[:4096].lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ResearchProviderError("Bing RSS response contains forbidden XML declarations")
        try:
            root = ET.fromstring(response_content)
        except (ET.ParseError, UnicodeError) as exc:
            raise ResearchProviderError("Bing RSS did not return valid bounded XML") from exc
        if root.tag != "rss":
            raise ResearchProviderError("Bing RSS response root is not rss")
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in root.findall("./channel/item"):
            url = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or url).strip()
            snippet = (item.findtext("description") or "").strip()
            published = (item.findtext("pubDate") or "").strip() or None
            parsed = urlsplit(url)
            if (
                not url
                or url in seen
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                continue
            seen.add(url)
            hits.append(
                SearchHit(
                    url=url,
                    title=normalize_research_text(title),
                    snippet=normalize_research_text(snippet),
                    engine=self.name,
                    published_at=published,
                )
            )
            if len(hits) >= limit:
                break
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=requested_at,
            raw_response_sha256=hashlib.sha256(response_content).hexdigest(),
            hits=tuple(hits),
        )


class JinaSearchProvider:
    """Use Jina's real Search/Reader SERP endpoint with an env-referenced API key."""

    name = "jina-search"

    def __init__(
        self,
        *,
        endpoint: str = "https://s.jina.ai",
        api_key_env: str = "JINA_API_KEY",
        credential_handle: str = "jina-api-key",
        timeout_seconds: float = 60,
        source_environment: Mapping[str, str] | None = None,
        allow_rfc2544_synthetic_egress: bool = False,
    ) -> None:
        self.endpoint = _exact_jina_origin(endpoint, official_host="s.jina.ai")
        self._policy = UrlPolicy(
            allowed_domains=("s.jina.ai",),
            allow_rfc2544_synthetic_egress=allow_rfc2544_synthetic_egress,
        )
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env) is None:
            raise ResearchProviderError("Jina API key environment handle is invalid")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", credential_handle) is None:
            raise ResearchProviderError("Jina credential handle is invalid")
        self.api_key_env = api_key_env
        self.credential_handle = credential_handle
        self.timeout_seconds = timeout_seconds
        source = os.environ if source_environment is None else source_environment
        self._api_key = source.get(api_key_env)

    def sensitive_values(self, credential_handles: frozenset[str]) -> tuple[str, ...]:
        if self.credential_handle not in credential_handles:
            return ()
        return (self._api_key,) if self._api_key else ()

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 5,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        if self.credential_handle not in credential_handles:
            raise ResearchPermissionError(
                f"Jina Search requires authorized credential handle {self.credential_handle}"
            )
        api_key = self._api_key
        if not api_key:
            raise ResearchProviderError(
                f"Jina Search requires credential environment handle {self.api_key_env}"
            )
        requested_at = datetime.now(UTC)
        resolution = await self._policy.resolve(self.endpoint)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    self.endpoint,
                    params={"q": query.text},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                ) as response:
                    await _verify_response_route(
                        response,
                        policy=self._policy,
                        before=resolution,
                    )
                    if response.is_redirect:
                        raise ResearchProviderError("Jina Search redirects are forbidden")
                    response.raise_for_status()
                    response_content = await _read_response_bytes(
                        response,
                        maximum=_MAX_SEARCH_RESPONSE_BYTES,
                    )
        except httpx.HTTPError as exc:
            raise ResearchProviderError(f"Jina Search request failed: {exc}") from exc
        try:
            payload = json.loads(response_content)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ResearchProviderError("Jina Search did not return requested JSON") from exc
        raw_items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise ResearchProviderError("Jina Search JSON omitted its result list")
        hits: list[SearchHit] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title") or url),
                    snippet=str(item.get("description") or item.get("content") or ""),
                    engine=self.name,
                    published_at=str(item.get("publishedTime"))
                    if item.get("publishedTime")
                    else None,
                )
            )
            if len(hits) >= limit:
                break
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=requested_at,
            raw_response_sha256=hashlib.sha256(response_content).hexdigest(),
            hits=tuple(hits),
        )


class HttpFetcher:
    """Fetch source bodies with redirect-by-redirect policy checks and byte limits."""

    name = "controlled-http"
    _SUPPORTED_TYPES = (
        "text/",
        "application/json",
        "application/xml",
        "application/xhtml+xml",
    )

    def __init__(
        self,
        policy: UrlPolicy,
        *,
        timeout_seconds: float = 30,
        max_bytes: int = 8 * 1024 * 1024,
        max_redirects: int = 5,
        user_agent: str = "agent-world-foundry/0.2 research (+local evidence collector)",
    ) -> None:
        if max_bytes > MAX_RAW_DOCUMENT_BYTES:
            raise ValueError("HTTP source limit cannot exceed the fixed 8 MiB safety ceiling")
        self.policy = policy
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent

    async def fetch(
        self,
        url: str,
        *,
        source_policy: UrlPolicy | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument:
        del credential_handles
        policy = source_policy or self.policy
        requested_url = url
        current = url
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,text/plain,application/json",
            },
        ) as client:
            for redirect_count in range(self.max_redirects + 1):
                resolution = await policy.resolve(current)
                try:
                    async with client.stream("GET", current) as response:
                        assurance, addresses = await _verify_response_route(
                            response,
                            policy=policy,
                            before=resolution,
                        )
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise ResearchProviderError("redirect response omitted Location")
                            if redirect_count == self.max_redirects:
                                raise ResearchProviderError("source exceeded redirect limit")
                            current = urljoin(current, location)
                            continue
                        response.raise_for_status()
                        media_type = (
                            response.headers.get("content-type", "").split(";", 1)[0].lower()
                        )
                        if not any(media_type.startswith(item) for item in self._SUPPORTED_TYPES):
                            raise ResearchProviderError(
                                f"unsupported evidence media type: {media_type}"
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                raise ResearchProviderError("source exceeded configured byte limit")
                        return FetchedDocument(
                            requested_url=requested_url,
                            final_url=str(response.url),
                            fetched_at=datetime.now(UTC),
                            status_code=response.status_code,
                            media_type=media_type or "application/octet-stream",
                            body=bytes(body),
                            response_headers=tuple(
                                (key.lower(), value)
                                for key, value in response.headers.items()
                                if key.lower()
                                in {"content-type", "content-language", "etag", "last-modified"}
                            ),
                            fetcher=self.name,
                            network_assurance=assurance,
                            resolved_addresses=addresses,
                        )
                except httpx.HTTPError as exc:
                    raise ResearchProviderError(f"source fetch failed: {exc}") from exc
        raise ResearchProviderError("source fetch ended without a response")


class JinaReaderFetcher:
    """Explicit remote-reader fallback; it never hides that Jina transformed the source."""

    name = "jina-reader"

    def __init__(
        self,
        source_policy: UrlPolicy,
        *,
        base_url: str = "https://r.jina.ai",
        api_key_env: str | None = "JINA_API_KEY",
        credential_handle: str = "jina-api-key",
        timeout_seconds: float = 60,
        max_bytes: int = 8 * 1024 * 1024,
        source_environment: Mapping[str, str] | None = None,
        allow_rfc2544_synthetic_egress: bool = False,
    ) -> None:
        if max_bytes > MAX_RAW_DOCUMENT_BYTES:
            raise ValueError("Jina Reader limit cannot exceed the fixed 8 MiB safety ceiling")
        self.source_policy = source_policy
        self.base_url = _exact_jina_origin(base_url, official_host="r.jina.ai")
        self._origin_policy = UrlPolicy(
            allowed_domains=("r.jina.ai",),
            allow_rfc2544_synthetic_egress=allow_rfc2544_synthetic_egress,
        )
        if api_key_env is not None and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", api_key_env
        ) is None:
            raise ResearchProviderError("Jina API key environment handle is invalid")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", credential_handle) is None:
            raise ResearchProviderError("Jina credential handle is invalid")
        self.api_key_env = api_key_env
        self.credential_handle = credential_handle
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        source = os.environ if source_environment is None else source_environment
        self._api_key = source.get(api_key_env) if api_key_env is not None else None

    def sensitive_values(self, credential_handles: frozenset[str]) -> tuple[str, ...]:
        if self.api_key_env is None or self.credential_handle not in credential_handles:
            return ()
        return (self._api_key,) if self._api_key else ()

    async def fetch(
        self,
        url: str,
        *,
        source_policy: UrlPolicy | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument:
        policy = source_policy or self.source_policy
        await policy.validate(url)
        target = f"{self.base_url}/{quote(url, safe=':/')}"
        headers = {"Accept": "text/markdown"}
        if (
            self.api_key_env
            and self.credential_handle in credential_handles
            and (api_key := self._api_key)
        ):
            headers["Authorization"] = f"Bearer {api_key}"
        resolution = await self._origin_policy.resolve(target)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream("GET", target, headers=headers) as response:
                    assurance, addresses = await _verify_response_route(
                        response,
                        policy=self._origin_policy,
                        before=resolution,
                    )
                    if response.is_redirect:
                        raise ResearchProviderError("Jina Reader redirects are forbidden")
                    response.raise_for_status()
                    response_content = await _read_response_bytes(
                        response,
                        maximum=self.max_bytes,
                    )
        except httpx.HTTPError as exc:
            raise ResearchProviderError(f"Jina Reader fetch failed: {exc}") from exc
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            status_code=response.status_code,
            media_type="text/markdown",
            body=response_content,
            response_headers=(("x-agent-world-transformer", self.base_url),),
            fetcher=self.name,
            network_assurance=f"remote-reader-origin-only:{assurance}",
            resolved_addresses=addresses,
        )


_EXTRACT_WORKER_PROTOCOL = "agent-world.trafilatura-extract.v1"
_MAX_EXTRACT_WORKER_RESPONSE_BYTES = 4 * 1024 * 1024


class TrafilaturaExtractor:
    """Run native HTML parsing outside the long-lived Controller process.

    Trafilatura depends on lxml/libxml2.  A native allocator failure cannot be
    caught as a Python exception, so importing and executing it in the Foundry
    process would let one untrusted page terminate the entire durable run.  The
    worker remains a real Trafilatura extractor; this boundary only supervises
    its process lifecycle and validates a closed response protocol.
    """

    name = "trafilatura-subprocess"

    def __init__(
        self,
        *,
        min_characters: int = 200,
        timeout_seconds: float = 30,
        maximum_parallel_workers: int = 2,
    ) -> None:
        if min_characters < 1:
            raise ValueError("minimum extracted character count must be positive")
        if timeout_seconds <= 0:
            raise ValueError("extractor timeout must be positive")
        if maximum_parallel_workers < 1 or maximum_parallel_workers > 16:
            raise ValueError("extractor parallel worker limit must be within 1..16")
        self.min_characters = min_characters
        self.timeout_seconds = timeout_seconds
        self._worker_slots = asyncio.Semaphore(maximum_parallel_workers)
        self.version = importlib.metadata.version("trafilatura")

    async def extract(self, source: FetchedDocument) -> ExtractedDocument:
        if source.media_type in {"text/plain", "text/markdown"}:
            text = source.body.decode("utf-8", errors="replace").strip()
            title = None
        else:
            decoded = source.body.decode("utf-8", errors="replace")
            text = await self._extract_html(source.body, source.final_url)
            text = text.strip()
            match = re.search(r"<title[^>]*>(.*?)</title>", decoded, flags=re.I | re.S)
            title = re.sub(r"\s+", " ", match.group(1)).strip() if match else None
        text = normalize_research_text(text)
        title = (normalize_research_text(title) or None) if title is not None else None
        if len(text) < self.min_characters:
            raise ResearchProviderError(
                f"extracted source is too short to support evidence ({len(text)} characters)"
            )
        return ExtractedDocument(
            source=source,
            text=text,
            title=title,
            raw_sha256=hashlib.sha256(source.body).hexdigest(),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            extractor=self.name,
            extractor_version=self.version,
        )

    async def _extract_html(self, body: bytes, url: str) -> str:
        async with self._worker_slots:
            return await self._extract_html_in_worker(body, url)

    async def _extract_html_in_worker(self, body: bytes, url: str) -> str:
        request = json.dumps(
            {
                "protocol": _EXTRACT_WORKER_PROTOCOL,
                "body_base64": base64.b64encode(body).decode("ascii"),
                "url": url,
                "timeout_seconds": self.timeout_seconds,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "agent_world.research._extract_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(request),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ResearchProviderError(
                f"HTML extractor subprocess exceeded {self.timeout_seconds:g} seconds"
            ) from exc
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

        if process.returncode != 0:
            if process.returncode is not None and process.returncode < 0:
                reason = f"signal {-process.returncode}"
            else:
                reason = f"exit status {process.returncode}"
            raise ResearchProviderError(f"HTML extractor subprocess terminated by {reason}")
        if len(stdout) > _MAX_EXTRACT_WORKER_RESPONSE_BYTES:
            raise ResearchProviderError("HTML extractor response exceeded its fixed byte limit")
        try:
            response = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ResearchProviderError(
                "HTML extractor returned an invalid protocol response"
            ) from exc
        if not isinstance(response, dict) or response.get("protocol") != _EXTRACT_WORKER_PROTOCOL:
            raise ResearchProviderError("HTML extractor returned an invalid protocol envelope")
        if response.get("status") == "error":
            error_type = response.get("error_type")
            message = response.get("message")
            if not isinstance(error_type, str) or not isinstance(message, str):
                raise ResearchProviderError("HTML extractor returned an invalid error envelope")
            raise ResearchProviderError(f"HTML extractor failed ({error_type}): {message}")
        if set(response) != {"protocol", "status", "text"} or response.get("status") != "ok":
            raise ResearchProviderError("HTML extractor returned an invalid success envelope")
        text = response.get("text")
        if not isinstance(text, str):
            raise ResearchProviderError("HTML extractor returned non-text content")
        return text


__all__ = [
    "BingRssSearchProvider",
    "HttpFetcher",
    "JinaReaderFetcher",
    "JinaSearchProvider",
    "ResearchProviderError",
    "SearxngSearchProvider",
    "TrafilaturaExtractor",
    "UrlPolicy",
]

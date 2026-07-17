from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from agent_world.config import ResearchConfig
from agent_world.contracts import PermissionScope
from agent_world.research import (
    FetchedDocument,
    HttpFetcher,
    JinaReaderFetcher,
    JinaSearchProvider,
    ResearchAccessPolicy,
    ResearchPermissionError,
    ResearchProviderError,
    SearchQuery,
    SearxngSearchProvider,
    TrafilaturaExtractor,
    UrlPolicy,
)
from agent_world.research.security import (
    ResearchSafetyError,
    assert_secret_free,
    normalize_research_text,
)


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://s.jina.ai",
        "https://search.example.org",
        "https://s.jina.ai:444",
        "https://s.jina.ai./",
        "https://user@s.jina.ai",
        "https://s.jina.ai/search",
        "https://s.jina.ai?redirect=https://example.org",
    ),
)
def test_jina_search_provider_rejects_every_non_official_credential_origin(
    endpoint: str,
) -> None:
    with pytest.raises(ResearchProviderError):
        JinaSearchProvider(endpoint=endpoint)


def test_jina_reader_provider_and_config_repeat_exact_origin_validation() -> None:
    with pytest.raises(ResearchProviderError):
        JinaReaderFetcher(UrlPolicy(), base_url="https://reader.example.org")
    with pytest.raises(ValidationError):
        ResearchConfig(
            provider="jina",
            jina_api_key_environment="JINA_API_KEY",
            jina_reader_url=HttpUrl("https://r.jina.ai:8443"),
        )

    config = ResearchConfig(
        provider="jina",
        jina_api_key_environment="JINA_API_KEY",
    )
    assert str(config.jina_search_url) == "https://s.jina.ai/"
    assert str(config.jina_reader_url) == "https://r.jina.ai/"


@pytest.mark.asyncio
async def test_real_html_extraction_is_parallel_and_native_parser_stays_out_of_parent() -> None:
    body = (
        "<html><head><title>Hotel booking reference</title></head><body><main>"
        "<h1>Reservation workflow</h1><p>"
        + (
            "A guest selects dates and room inventory before confirming a reservation. "
            "The service records availability, confirmation, and cancellation state. "
            * 12
        )
        + "</p></main></body></html>"
    ).encode("utf-8")
    source = FetchedDocument(
        requested_url="https://docs.example.org/hotel-booking",
        final_url="https://docs.example.org/hotel-booking",
        fetched_at=datetime.now(UTC),
        status_code=200,
        media_type="text/html",
        body=body,
    )
    extractor = TrafilaturaExtractor(timeout_seconds=10)

    documents = await asyncio.gather(*(extractor.extract(source) for _ in range(8)))

    assert {item.extractor for item in documents} == {"trafilatura-subprocess"}
    assert {item.title for item in documents} == {"Hotel booking reference"}
    assert len({item.text_sha256 for item in documents}) == 1
    assert all("confirming a reservation" in item.text for item in documents)


def test_research_provider_parent_does_not_import_native_html_parser() -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; import agent_world.research.providers; "
                "print('trafilatura' in sys.modules, 'lxml' in sys.modules)"
            ),
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.stdout.strip() == "False False"


@pytest.mark.asyncio
async def test_jina_search_requires_the_framework_credential_handle_before_network() -> None:
    provider = JinaSearchProvider(
        api_key_env="ENVIRONMENT_NAME_THAT_IS_NOT_READ_WITHOUT_PERMISSION"
    )

    with pytest.raises(ResearchPermissionError, match="authorized credential handle"):
        await provider.search(SearchQuery("agent environment tools"))


def test_research_access_intersects_request_and_run_permissions() -> None:
    request = PermissionScope(
        network_domains=("**.example.org",),
        tool_allowlist=("research.search", "research.fetch"),
        credential_handles=("jina-api-key", "request-only"),
    )
    run = PermissionScope(
        network_domains=("docs.example.org",),
        tool_allowlist=("research.search", "research.fetch"),
        credential_handles=("jina-api-key", "run-only"),
    )

    access = ResearchAccessPolicy.create(
        request_permissions=request,
        run_permissions=run,
        allowed_source_kinds=("web",),
    )

    assert access.credential_handles == frozenset({"jina-api-key"})
    with pytest.raises(ResearchProviderError, match="outside the allowlist"):
        asyncio.run(access.source_policy.validate("https://api.example.org/reference"))


def test_research_access_denies_unimplemented_source_kinds_and_explicit_tool_capability() -> None:
    with pytest.raises(ResearchPermissionError, match="exactly the web"):
        ResearchAccessPolicy.create(
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("repository",),
        )
    with pytest.raises(ResearchPermissionError, match="exactly the web"):
        ResearchAccessPolicy.create(
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web", "repository"),
        )
    with pytest.raises(ResearchPermissionError, match="research.fetch"):
        ResearchAccessPolicy.create(
            request_permissions=PermissionScope(tool_allowlist=("research.search",)),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web",),
        )


@pytest.mark.asyncio
async def test_empty_network_domains_still_deny_private_sources() -> None:
    access = ResearchAccessPolicy.create(
        request_permissions=PermissionScope(),
        run_permissions=PermissionScope(),
        allowed_source_kinds=("web",),
    )

    with pytest.raises(ResearchProviderError, match="private, loopback"):
        await access.source_policy.validate("http://127.0.0.1/reference")
    with pytest.raises(ResearchProviderError, match="userinfo"):
        await access.source_policy.validate("https://user@example.org/reference")
    with pytest.raises(ResearchProviderError, match="credential-bearing"):
        await access.source_policy.validate("https://example.org/reference?access_token=value")


@pytest.mark.asyncio
async def test_rfc2544_synthetic_egress_is_explicit_and_never_implied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def synthetic_getaddrinfo(
        host: str,
        port: int,
        *,
        type: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert host == "public.example"
        assert type == __import__("socket").SOCK_STREAM
        return [
            (
                __import__("socket").AF_INET,
                __import__("socket").SOCK_STREAM,
                6,
                "",
                ("198.18.0.160", port),
            )
        ]

    monkeypatch.setattr("socket.getaddrinfo", synthetic_getaddrinfo)
    default_policy = UrlPolicy()
    with pytest.raises(ResearchProviderError, match="reserved source address denied"):
        await default_policy.resolve("https://public.example/reference")

    explicit_policy = UrlPolicy(allow_rfc2544_synthetic_egress=True)
    resolution = await explicit_policy.resolve("https://public.example/reference")
    assert resolution.uses_synthetic_egress
    assert tuple(str(item) for item in resolution.addresses) == ("198.18.0.160",)


def test_research_content_is_normalized_and_secret_scanned_without_truncation() -> None:
    source = "First\r\nSecond\u0000Third\n" + ("complete body " * 100)
    normalized = normalize_research_text(source)
    assert normalized.startswith("First\nSecond Third\n")
    assert normalized.endswith("complete body")
    assert len(normalized) > 600

    assert_secret_free(
        b'api_key = "your_example_api_key"',
        context="documented placeholder",
    )
    with pytest.raises(ResearchSafetyError, match="credential-like"):
        assert_secret_free(
            b'{"api_key": "a8DkP7mZ2qL9sW4vN6xR"}',
            context="research body",
        )


_SERVER_SOURCE = r'''
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/search?"):
            body = json.dumps(
                {
                    "results": [
                        {
                            "url": f"http://127.0.0.1:{self.server.server_port}/body",
                            "title": "Local real-process result",
                            "content": "selection snippet, not evidence",
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/body")
            self.end_headers()
            return
        body = (
            "real local source body with enough content for transport verification. " * 8
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
'''


@pytest.mark.asyncio
async def test_http_fetcher_uses_real_peer_and_revalidates_each_redirect_hop(
    tmp_path: Path,
) -> None:
    server_path = _write_server_source(tmp_path)
    executable = _resolved_python()
    process = await asyncio.create_subprocess_exec(
        executable,
        str(server_path),
        cwd=str(tmp_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        port_text = (await asyncio.wait_for(process.stdout.readline(), timeout=5)).decode().strip()
        assert port_text.isdigit()
        port = int(port_text)
        policy = UrlPolicy(
            allowed_domains=("127.0.0.1",),
            private_host_exceptions=("127.0.0.1",),
        )
        fetcher = HttpFetcher(policy, timeout_seconds=5)

        search = SearxngSearchProvider(
            f"http://127.0.0.1:{port}",
            timeout_seconds=5,
            allow_private_endpoint=True,
        )
        record = await search.search(SearchQuery("real endpoint capability"), limit=1)
        assert record.hits[0].snippet == "selection snippet, not evidence"
        public_source_access = ResearchAccessPolicy.create(
            request_permissions=PermissionScope(),
            run_permissions=PermissionScope(),
            allowed_source_kinds=("web",),
        )
        with pytest.raises(ResearchProviderError, match="private, loopback"):
            await public_source_access.source_policy.validate(record.hits[0].url)

        document = await fetcher.fetch(f"http://127.0.0.1:{port}/body")

        assert document.status_code == 200
        assert document.resolved_addresses == ("127.0.0.1",)
        assert document.network_assurance == "peer-address+dns-stability"
        with pytest.raises(ResearchProviderError, match="outside the allowlist"):
            await fetcher.fetch(f"http://127.0.0.1:{port}/redirect")
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()


def _write_server_source(root: Path) -> Path:
    server_path = root / "research-source-server.py"
    server_path.write_text(_SERVER_SOURCE, encoding="utf-8")
    return server_path


def _resolved_python() -> str:
    return os.path.realpath(sys.executable)

import json
import textwrap

from agent_world.config import load_research_config
from agent_world.research import lightweight
from agent_world.research import providers


def _research_env(tmp_path, research: str, **values: str) -> dict[str, str]:
    config_path = tmp_path / "agent-world.yaml"
    config_path.write_text(
        "research:\n" + textwrap.indent(textwrap.dedent(research).strip() + "\n", "  "),
        encoding="utf-8",
    )
    return {"AGENT_WORLD_CONFIG": str(config_path), **values}


def test_jina_provider_searches_and_fetches_markdown(monkeypatch):
    calls = []

    def stub_urlopen(request, timeout):
        calls.append({"url": request.full_url, "headers": dict(request.header_items()), "timeout": timeout})
        if request.full_url.startswith("https://s.jina.ai"):
            return _Response(
                """
Title: Example One
URL Source: https://docs.example/one

Title: Example Two
URL Source: https://docs.example/two
"""
            )
        if "docs.example/one" in request.full_url:
            return _Response("# Example One\n\nFetched markdown one.")
        if "docs.example/two" in request.full_url:
            return _Response("# Example Two\n\nFetched markdown two.")
        raise AssertionError(f"unexpected URL: {request.full_url}")

    monkeypatch.setattr(providers.urllib.request, "urlopen", stub_urlopen)

    results = providers.jina_results(
        "https://s.jina.ai",
        "https://r.jina.ai",
        "jina-test-key",
        ["example query"],
        max_results=2,
    )

    assert [item["uri"] for item in results] == ["https://docs.example/one", "https://docs.example/two"]
    assert results[0]["title"] == "Example One"
    assert "Fetched markdown one" in results[0]["snippet"]
    assert all(len(item["version_or_hash"]) == 64 for item in results)
    assert any(call["headers"].get("Authorization") == "Bearer jina-test-key" for call in calls)
    assert all(call["headers"].get("User-agent") or call["headers"].get("User-Agent") for call in calls)


def test_jina_research_backend_collects_candidates_without_recording_secret(tmp_path, monkeypatch):
    captured = {}

    def stub_jina_results(search_url, reader_url, api_key, queries, *, max_results):
        captured.update(
            {
                "search_url": search_url,
                "reader_url": reader_url,
                "api_key": api_key,
                "queries": queries,
                "max_results": max_results,
            }
        )
        return [
            {
                "kind": "api_docs",
                "uri": "https://docs.example/workflow",
                "title": "Workflow Docs",
                "snippet": "# Workflow Docs\n\nFetched markdown.",
                "version_or_hash": "a" * 64,
            }
        ]

    monkeypatch.setattr(lightweight, "jina_results", stub_jina_results)
    context = _ResearchContext(
        _research_env(
            tmp_path,
            """
            backend: jina
            jina_search_url: https://s.jina.ai
            jina_reader_url: https://r.jina.ai
            jina_api_key_env: JINA_API_KEY
            max_results: 3
            """,
            JINA_API_KEY="secret-value",
        )
    )

    packet = lightweight.collect_research_candidates(context, load_research_config(context.config.env))

    assert captured["api_key"] == "secret-value"
    assert captured["max_results"] == 3
    assert any(source["uri_or_path"] == "https://docs.example/workflow" for source in packet["candidates"])
    serialized = json.dumps(packet, sort_keys=True)
    assert "secret-value" not in serialized


def test_default_research_backend_uses_jina_configured_key_env_without_secret(monkeypatch):
    captured = {}

    def stub_jina_results(search_url, reader_url, api_key, queries, *, max_results):
        captured.update(
            {
                "search_url": search_url,
                "reader_url": reader_url,
                "api_key": api_key,
                "queries": queries,
                "max_results": max_results,
            }
        )
        return []

    monkeypatch.setattr(lightweight, "jina_results", stub_jina_results)
    context = _ResearchContext({})
    config = load_research_config(context.config.env)

    packet = lightweight.collect_research_candidates(context, config)

    assert config.backend == "jina"
    assert config.jina_api_key_env == "JINA_API_KEY"
    assert captured["search_url"] == "https://s.jina.ai"
    assert captured["reader_url"] == "https://r.jina.ai"
    assert captured["api_key"] == ""
    assert any(source["source_id"] == "source-raw-request" for source in packet["candidates"])


def test_research_backend_provider_failure_keeps_local_raw_request(tmp_path, monkeypatch):
    def failing_jina_results(*args, **kwargs):
        raise TimeoutError("jina timed out")

    monkeypatch.setattr(lightweight, "jina_results", failing_jina_results)
    context = _ResearchContext(
        _research_env(
            tmp_path,
            """
            backend: jina
            max_results: 3
            """,
        )
    )

    packet = lightweight.collect_research_candidates(context, load_research_config(context.config.env))

    assert any(source["source_id"] == "source-raw-request" for source in packet["candidates"])
    assert packet["provider_errors"] == [{"provider": "jina", "error": "jina timed out"}]
    assert any(item["source"] == "jina" for item in packet["rejected_sources"])


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.text.encode("utf-8")


class _ResearchConfig:
    run_id = "jina-test"
    raw_request = "Generate a workflow environment"
    source_paths = []

    def __init__(self, env):
        self.env = env


class _ResearchStore:
    root = None


class _ResearchContext:
    store = _ResearchStore()

    def __init__(self, env):
        self.config = _ResearchConfig(env)

    def artifact(self, artifact_type):
        assert artifact_type == "DomainPlan"
        return {
            "domain_seed": "env-jina-test",
            "raw_request": self.config.raw_request,
            "recognized_intents": ["workflow", "environment"],
        }

from __future__ import annotations

from pathlib import Path
import os
import tempfile
from typing import Any

from agent_world.artifacts import SOURCE_KINDS
from agent_world.config import ResearchConfig
from agent_world.research.providers import jina_results, local_source_results, process_results, searxng_results, sha256_file


RAW_REQUEST_SOURCE_ID = "source-raw-request"


def collect_research_candidates(context: Any, config: ResearchConfig) -> dict[str, Any]:
    root = _source_root(context)
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "raw-request.md"
    request_path.write_text(_raw_request_document(context), encoding="utf-8")
    queries = _query_plan(context)[: config.max_queries]
    local_paths = [request_path] + [Path(path) for path in context.config.source_paths]
    raw_results = local_source_results(local_paths)
    provider_errors = []
    if config.backend == "searxng":
        try:
            raw_results.extend(searxng_results(config.searxng_url, queries, max_results=config.max_results))
        except Exception as exc:
            provider_errors.append({"provider": "searxng", "error": str(exc)})
    elif config.backend == "jina":
        try:
            raw_results.extend(
                jina_results(
                    config.jina_search_url,
                    config.jina_reader_url,
                    _secret_from_env(context, config.jina_api_key_env),
                    queries,
                    max_results=config.max_results,
                )
            )
        except Exception as exc:
            provider_errors.append({"provider": "jina", "error": str(exc)})
    elif config.backend == "process":
        try:
            raw_results.extend(process_results(config.process_command, {"queries": queries, "raw_request": context.config.raw_request}, max_results=config.max_results))
        except Exception as exc:
            provider_errors.append({"provider": "process", "error": str(exc)})
    elif config.backend not in {"local", ""}:
        provider_errors.append({"provider": config.backend, "error": "unknown research backend"})
    rejected = []
    candidates = []
    seen: set[str] = set()
    for index, result in enumerate(raw_results, start=1):
        if result.get("kind") == "rejected":
            rejected.append({"source": str(result.get("uri", "")), "reason": str(result.get("reason", "rejected"))})
            continue
        uri = str(result.get("uri", ""))
        if not uri or uri in seen:
            continue
        seen.add(uri)
        kind = str(result.get("kind") or "manual_note")
        if kind not in SOURCE_KINDS:
            kind = "api_docs"
        source_id = RAW_REQUEST_SOURCE_ID if Path(uri).resolve() == request_path.resolve() else f"source-research-{index}"
        version = str(result.get("version_or_hash") or "")
        candidates.append(
            {
                "source_id": source_id,
                "kind": kind,
                "uri_or_path": uri,
                "version_or_hash": version,
                "license": "user_supplied" if kind in {"manual_note", "local_files"} else "unknown",
                "auth_requirement": "none",
                "network_requirement": "none" if kind in {"manual_note", "local_files"} else "optional",
                "security_note": "Research source selected by configured source discovery executor.",
                "object_kind": "request_source" if source_id == RAW_REQUEST_SOURCE_ID else "research_result",
                "name": str(result.get("title") or Path(uri).name or source_id),
                "evidence_refs": [f"{source_id}#sha256:{version}"] if version else [source_id],
                "snippet": str(result.get("snippet") or "")[:2000],
            }
        )
    rejected.extend({"source": item["provider"], "reason": item["error"]} for item in provider_errors)
    return {
        "planned_environment_id": context.artifact("DomainPlan")["domain_seed"],
        "queries": queries,
        "candidates": candidates,
        "provider_errors": provider_errors,
        "rejected_sources": rejected,
    }


def _raw_request_document(context: Any) -> str:
    domain_plan = context.artifact("DomainPlan")
    return (
        "# Raw Request Source\n\n"
        f"run_id: {context.config.run_id}\n"
        f"environment_id: {domain_plan['domain_seed']}\n\n"
        "## Request\n\n"
        f"{domain_plan['raw_request']}\n"
    )


def _source_root(context: Any) -> Path:
    if context.store.root:
        return context.store.root / "sources" / "research" / context.artifact("DomainPlan")["domain_seed"]
    return Path(tempfile.mkdtemp(prefix="agent-world-research-source-"))


def _query_plan(context: Any) -> list[str]:
    domain = context.artifact("DomainPlan")
    terms = [str(item) for item in domain.get("recognized_intents", [])[:5]]
    query = " ".join(terms) or context.config.raw_request
    return [query, f"{query} workflow tools", f"{query} verification tasks"]


def _secret_from_env(context: Any, env_name: str) -> str:
    if not env_name:
        return ""
    run_env = context.config.env or {}
    return str(run_env.get(env_name) or os.environ.get(env_name) or "")

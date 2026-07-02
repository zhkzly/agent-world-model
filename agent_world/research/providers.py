from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any
import urllib.parse
import urllib.request


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_source_results(paths: list[Path]) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        resolved = Path(path).resolve()
        if not resolved.is_file():
            results.append({"kind": "rejected", "uri": str(path), "reason": "source path is not a file"})
            continue
        results.append(
            {
                "kind": "local_files",
                "uri": str(resolved),
                "title": resolved.name,
                "snippet": resolved.read_text(encoding="utf-8", errors="replace")[:1000],
                "version_or_hash": sha256_file(resolved),
            }
        )
    return results


def searxng_results(base_url: str, queries: list[str], *, max_results: int) -> list[dict[str, Any]]:
    if not base_url:
        raise ValueError("research.searxng_url is required for searxng research backend")
    output: list[dict[str, Any]] = []
    root = base_url.rstrip("/")
    for query in queries:
        params = urllib.parse.urlencode({"q": query, "format": "json"})
        with urllib.request.urlopen(f"{root}/search?{params}", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for item in payload.get("results", [])[:max_results]:
            url = str(item.get("url") or item.get("parsed_url") or "")
            output.append(
                {
                    "kind": "api_docs",
                    "uri": url,
                    "title": str(item.get("title") or url or query),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                    "version_or_hash": hashlib.sha256((url + query).encode("utf-8")).hexdigest(),
                }
            )
    return output[:max_results]


def jina_results(
    search_url: str,
    reader_url: str,
    api_key: str,
    queries: list[str],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    if not search_url:
        raise ValueError("research.jina_search_url is required for jina research backend")
    output: list[dict[str, Any]] = []
    for query in queries:
        search_text = _jina_http_text(_jina_search_endpoint(search_url, query), api_key=api_key)
        for candidate in _parse_jina_search_results(search_text, max_results=max_results):
            markdown = ""
            if reader_url and candidate["uri"]:
                try:
                    markdown = _jina_http_text(_jina_reader_endpoint(reader_url, candidate["uri"]), api_key=api_key)
                except Exception:
                    markdown = ""
            content = markdown or candidate["snippet"] or search_text
            output.append(
                {
                    "kind": "api_docs",
                    "uri": candidate["uri"],
                    "title": candidate["title"],
                    "snippet": content[:2000],
                    "version_or_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            )
            if len(output) >= max_results:
                return output
    return output[:max_results]


def process_results(command: str, packet: dict[str, Any], *, max_results: int) -> list[dict[str, Any]]:
    if not command:
        raise ValueError("research.process_command is required for process research backend")
    completed = subprocess.run(
        shlex.split(command),
        input=json.dumps(packet, sort_keys=True),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"research command exited {completed.returncode}")
    payload = json.loads(completed.stdout or "{}")
    results = payload.get("results", payload if isinstance(payload, list) else [])
    if not isinstance(results, list):
        raise ValueError("research command must return a JSON object with results[] or a JSON list")
    normalized = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or item.get("url") or item.get("path") or "")
        normalized.append(
            {
                "kind": str(item.get("kind") or "api_docs"),
                "uri": uri,
                "title": str(item.get("title") or uri or "research result"),
                "snippet": str(item.get("snippet") or item.get("content") or ""),
                "version_or_hash": str(item.get("version_or_hash") or hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest()),
            }
        )
    return normalized


def _jina_search_endpoint(search_url: str, query: str) -> str:
    root = search_url.rstrip("/")
    separator = "&" if "?" in root else "?"
    return f"{root}{separator}{urllib.parse.urlencode({'q': query})}"


def _jina_reader_endpoint(reader_url: str, target_url: str) -> str:
    encoded = urllib.parse.quote(target_url, safe=":/?&=%-._~+")
    return f"{reader_url.rstrip('/')}/{encoded}"


def _jina_http_text(url: str, *, api_key: str) -> str:
    headers = {"Accept": "text/plain", "User-Agent": "agent-world-model/0.1 (+https://jina.ai/reader)"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_jina_search_results(text: str, *, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        url = _url_from_jina_line(line)
        if not url:
            continue
        title = _nearest_title(lines, index) or url
        snippet = "\n".join(item.strip() for item in lines[index + 1 : index + 5] if item.strip())
        results.append({"uri": url, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    if results:
        return results
    urls = re.findall(r"https?://[^\s)\]>\"']+", text)
    for url in urls[:max_results]:
        results.append({"uri": url.rstrip(".,;"), "title": url.rstrip(".,;"), "snippet": text[:1000]})
    return results


def _url_from_jina_line(line: str) -> str:
    stripped = line.strip()
    for prefix in ["URL Source:", "URL:", "Source:"]:
        if stripped.startswith(prefix):
            candidate = stripped[len(prefix) :].strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate.rstrip(".,;")
    match = re.search(r"https?://[^\s)\]>\"']+", stripped)
    if match:
        return match.group(0).rstrip(".,;")
    return ""


def _nearest_title(lines: list[str], index: int) -> str:
    for line in reversed(lines[max(0, index - 4) : index]):
        title = line.strip().strip("#*-0123456789.[] ")
        if not title or title.startswith(("URL", "Source", "Markdown Content")):
            continue
        if title.startswith("Title:"):
            title = title[len("Title:") :].strip()
        if title:
            return title
    return ""

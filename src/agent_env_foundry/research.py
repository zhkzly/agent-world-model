"""Evidence-grounded Research and deterministic Development Brief derivation.

Research exposes one Builder/Qualifier input: a Host-derived immutable
BuilderProjection from the accepted Brief. Search candidates remain
discovery-only. Only exact retained HTTP response bytes and Crawl4AI-derived
passages can close a factual claim.

This module deliberately owns no Builder, environment candidate, Qualification,
release publication, Task, verifier, reward, Registry, or workflow graph.
"""

from __future__ import annotations

import codecs
import hashlib
import importlib.metadata
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import rfc8785
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from jsonschema import Draft202012Validator

__all__ = [
    "BuilderProjection",
    "EvidenceReview",
    "DevelopmentBrief",
    "DraftValidationError",
    "EvidenceIndex",
    "EvidenceIntegrityError",
    "EvidenceStore",
    "NeedRecord",
    "NotReleased",
    "ResearchBudget",
    "ResearchConfig",
    "ResearchFailure",
    "ResearchReady",
    "ResearchTools",
    "Unsupported",
    "aggregate_evidence_review",
    "derive_development_brief",
    "finalize_research",
    "sanitize_url",
]

_CRAWL4AI_VERSION = "0.9.2"
_SOURCE_ID = re.compile(r"^source-revision-[0-9a-f]{64}$")
_EXTRACTION_ID = re.compile(r"^extraction-[0-9a-f]{64}$")
_SOURCE_HANDLE = re.compile(r"^S[1-9][0-9]*$")
_EVIDENCE_HANDLE = re.compile(r"^E[1-9][0-9]*$")
_CANDIDATE_HANDLE = re.compile(r"^C[1-9][0-9]*$")
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "passwd",
    "secret",
    "sig",
    "signature",
    "token",
}
_REQUIREMENT_SECTIONS = (
    "capabilities",
    "workflows",
    "invariants",
    "refusals",
    "initial_world",
)
_FORBIDDEN_DRAFT_PATTERNS = (
    re.compile(r"\bcreate\s+table\b", re.IGNORECASE),
    re.compile(r"\binput_schema\b|\boutput_schema\b", re.IGNORECASE),
    re.compile(r"\btoolspec\b", re.IGNORECASE),
    re.compile(r"\btaskpack\b|\btask\s+schema\b", re.IGNORECASE),
    re.compile(r"\bverifier\b.*\breward\b|\breward\b.*\bverifier\b", re.IGNORECASE),
    re.compile(r"\bscalar\s+reward\b|\breward\s+schema\b", re.IGNORECASE),
)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _handle_path_order(path: Path) -> tuple[str, int]:
    stem = path.stem
    suffix = stem[1:]
    return stem[:1], int(suffix) if suffix.isdigit() else 0


class ResearchFailure(RuntimeError):
    """Typed fail-closed Research error with actionable original failure facts."""

    def __init__(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{phase}:{code}: {message}")
        self.phase = phase
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_document(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "code": self.code,
            "message": self.message,
            "details": _json_copy(self.details),
        }


class EvidenceIntegrityError(ResearchFailure):
    """Retained evidence no longer matches its content-bound identity."""


class DraftValidationError(ValueError):
    """The Research Draft violates its structured or evidence contract."""


def _failure(
    phase: str,
    code: str,
    message: str,
    *,
    original_code: str | int,
    original_message: str,
    **details: Any,
) -> ResearchFailure:
    return ResearchFailure(
        phase=phase,
        code=code,
        message=message,
        details={
            "original_code": original_code,
            "original_message": original_message,
            **details,
        },
    )


@dataclass(frozen=True)
class ResearchConfig:
    """Non-secret Research transport and extraction ceilings."""

    searxng_url: str = "http://127.0.0.1:8080"
    request_timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_results_per_query: int = 10
    max_bytes_per_source: int = 2_000_000
    max_passages_per_read: int = 8
    max_visible_passages_per_run: int = 32
    max_passage_characters: int = 2_000

    def __post_init__(self) -> None:
        parsed = urlsplit(self.searxng_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("searxng_url must be an absolute http(s) URL")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        for name in (
            "max_redirects",
            "max_results_per_query",
            "max_bytes_per_source",
            "max_passages_per_read",
            "max_visible_passages_per_run",
            "max_passage_characters",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class ResearchBudget:
    """Safety ceilings.  They never prescribe a fixed Research call recipe."""

    max_search_calls: int = 12
    max_fetches: int = 16
    max_total_bytes: int = 16_000_000

    def __post_init__(self) -> None:
        for name in ("max_search_calls", "max_fetches", "max_total_bytes"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class SourceRevision:
    source_revision_id: str
    requested_url: str
    final_url: str
    redirect_chain: tuple[dict[str, Any], ...]
    status_code: int
    media_type: str
    content_type: str
    charset: str
    content_encoding: str
    retrieved_at: str
    body_digest: str
    byte_count: int
    body_mirrors: tuple[str, ...]
    body: bytes = field(repr=False)

    def to_document(self) -> dict[str, Any]:
        return {
            "source_revision_id": self.source_revision_id,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "redirect_chain": [_json_copy(item) for item in self.redirect_chain],
            "status_code": self.status_code,
            "media_type": self.media_type,
            "content_type": self.content_type,
            "charset": self.charset,
            "content_encoding": self.content_encoding,
            "retrieved_at": self.retrieved_at,
            "body_digest": self.body_digest,
            "byte_count": self.byte_count,
            "body_mirrors": list(self.body_mirrors),
        }


class EvidenceStore:
    """Run-scoped immutable SourceRevision and extraction storage.

    This is intentionally consumer-local storage, not a general content-addressed
    platform.  Every read rechecks the body digest and the identity preimage so a
    third party can inspect the ordinary bytes and JSON independently.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("evidence root must not be a symlink")
        self._revisions = self.root / "source-revisions"
        self._extractions = self.root / "extractions"
        self._source_handles = self.root / "handles" / "sources"
        self._evidence_handles = self.root / "handles" / "evidence"
        self._revisions.mkdir(parents=True, exist_ok=True)
        self._extractions.mkdir(parents=True, exist_ok=True)
        self._source_handles.mkdir(parents=True, exist_ok=True)
        self._evidence_handles.mkdir(parents=True, exist_ok=True)

    def revision_body_path(self, source_revision_id: str) -> Path:
        self._validate_source_id(source_revision_id)
        return self._revisions / source_revision_id / "body.bin"

    def retain_revision(self, *, body: bytes, metadata: Mapping[str, Any]) -> SourceRevision:
        body_digest = _sha256(body)
        mirrors = tuple(
            sorted(
                item["source_revision_id"]
                for item in self._revision_documents()
                if item["body_digest"] == body_digest
            )
        )
        identity_document = {
            **_json_copy(dict(metadata)),
            "body_digest": body_digest,
            "byte_count": len(body),
            "body_mirrors": list(mirrors),
        }
        source_revision_id = f"source-revision-{_sha256(_canonical_bytes(identity_document))}"
        document = {"source_revision_id": source_revision_id, **identity_document}
        directory = self._revisions / source_revision_id
        if directory.exists():
            existing = self.read_revision(source_revision_id)
            if existing.body != body or existing.to_document() != document:
                raise EvidenceIntegrityError(
                    phase="evidence",
                    code="source_revision_collision",
                    message="existing SourceRevision differs from its content-bound identity",
                    details={"source_revision_id": source_revision_id},
                )
            return existing
        directory.mkdir(mode=0o700)
        body_path = directory / "body.bin"
        metadata_path = directory / "metadata.json"
        body_path.write_bytes(body)
        metadata_path.write_bytes(_canonical_bytes(document))
        body_path.chmod(0o444)
        metadata_path.chmod(0o444)
        return self.read_revision(source_revision_id)

    def read_revision(self, source_revision_id: str) -> SourceRevision:
        self._validate_source_id(source_revision_id)
        directory = self._revisions / source_revision_id
        try:
            document = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            body = (directory / "body.bin").read_bytes()
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError(
                phase="evidence",
                code="source_revision_unreadable",
                message=f"cannot read retained SourceRevision {source_revision_id}",
                details={
                    "source_revision_id": source_revision_id,
                    "original_code": type(exc).__name__,
                    "original_message": str(exc),
                },
            ) from exc
        if not isinstance(document, dict):
            raise self._integrity(source_revision_id, "metadata is not an object")
        declared_digest = document.get("body_digest")
        actual_digest = _sha256(body)
        if declared_digest != actual_digest:
            raise self._integrity(
                source_revision_id,
                f"body digest mismatch: declared {declared_digest}, actual {actual_digest}",
            )
        if document.get("byte_count") != len(body):
            raise self._integrity(source_revision_id, "retained byte count mismatch")
        identity_document = dict(document)
        declared_id = identity_document.pop("source_revision_id", None)
        actual_id = f"source-revision-{_sha256(_canonical_bytes(identity_document))}"
        if declared_id != source_revision_id or actual_id != source_revision_id:
            raise self._integrity(source_revision_id, "SourceRevision identity preimage mismatch")
        try:
            return SourceRevision(
                source_revision_id=source_revision_id,
                requested_url=str(document["requested_url"]),
                final_url=str(document["final_url"]),
                redirect_chain=tuple(cast(list[dict[str, Any]], document["redirect_chain"])),
                status_code=int(document["status_code"]),
                media_type=str(document["media_type"]),
                content_type=str(document["content_type"]),
                charset=str(document["charset"]),
                content_encoding=str(document["content_encoding"]),
                retrieved_at=str(document["retrieved_at"]),
                body_digest=actual_digest,
                byte_count=len(body),
                body_mirrors=tuple(cast(list[str], document["body_mirrors"])),
                body=body,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise self._integrity(source_revision_id, f"invalid metadata fields: {exc}") from exc

    def retain_extraction(self, document: Mapping[str, Any]) -> dict[str, Any]:
        identity_document = _json_copy(dict(document))
        extraction_id = f"extraction-{_sha256(_canonical_bytes(identity_document))}"
        complete = {"extraction_id": extraction_id, **identity_document}
        path = self._extractions / f"{extraction_id}.json"
        if path.exists():
            existing = self.read_extraction(extraction_id)
            if existing != complete:
                raise EvidenceIntegrityError(
                    phase="evidence",
                    code="extraction_collision",
                    message="existing extraction differs from its content-bound identity",
                    details={"extraction_id": extraction_id},
                )
            return existing
        path.write_bytes(_canonical_bytes(complete))
        path.chmod(0o444)
        return self.read_extraction(extraction_id)

    def read_extraction(self, extraction_id: str) -> dict[str, Any]:
        if not _EXTRACTION_ID.fullmatch(extraction_id):
            raise EvidenceIntegrityError(
                phase="evidence",
                code="invalid_extraction_id",
                message=f"invalid extraction identity {extraction_id!r}",
                details={"extraction_id": extraction_id},
            )
        path = self._extractions / f"{extraction_id}.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError(
                phase="evidence",
                code="extraction_unreadable",
                message=f"cannot read extraction {extraction_id}",
                details={
                    "extraction_id": extraction_id,
                    "original_code": type(exc).__name__,
                    "original_message": str(exc),
                },
            ) from exc
        if not isinstance(document, dict):
            raise EvidenceIntegrityError(
                phase="evidence",
                code="extraction_corrupt",
                message="extraction document is not an object",
                details={"extraction_id": extraction_id},
            )
        preimage = dict(document)
        declared_id = preimage.pop("extraction_id", None)
        actual_id = f"extraction-{_sha256(_canonical_bytes(preimage))}"
        if declared_id != extraction_id or actual_id != extraction_id:
            raise EvidenceIntegrityError(
                phase="evidence",
                code="extraction_digest_mismatch",
                message="extraction identity preimage mismatch",
                details={"extraction_id": extraction_id},
            )
        return cast(dict[str, Any], document)

    def resolve_passage(
        self, source_revision_id: str, passage_id: str
    ) -> tuple[SourceRevision, dict[str, Any], dict[str, Any]]:
        revision = self.read_revision(source_revision_id)
        for path in sorted(self._extractions.glob("extraction-*.json")):
            extraction = self.read_extraction(path.stem)
            if extraction.get("source_revision_id") != source_revision_id:
                continue
            if extraction.get("source_body_digest") != revision.body_digest:
                raise self._integrity(source_revision_id, "extraction binds different source bytes")
            for passage in cast(list[dict[str, Any]], extraction.get("passages", [])):
                if passage.get("passage_id") == passage_id:
                    return revision, extraction, passage
        raise DraftValidationError(
            f"evidence passage {passage_id!r} does not exist for SourceRevision "
            f"{source_revision_id!r}"
        )

    def retain_source_handle(self, source_revision_id: str) -> str:
        """Persist a short run-local source handle for a protected revision ID."""
        self.read_revision(source_revision_id)
        for path in sorted(self._source_handles.glob("S*.json"), key=_handle_path_order):
            document = self._read_handle_document(path, kind="source")
            if document.get("source_revision_id") == source_revision_id:
                return str(document["handle"])
        handle = f"S{self._next_handle_number(self._source_handles, _SOURCE_HANDLE)}"
        self._write_handle_document(
            self._source_handles / f"{handle}.json",
            {"handle": handle, "source_revision_id": source_revision_id},
        )
        return handle

    def resolve_source_handle(self, source_handle: str) -> str:
        """Resolve an exact short source handle without guessing or autocorrection."""
        if not _SOURCE_HANDLE.fullmatch(source_handle):
            raise DraftValidationError(
                f"invalid source handle {source_handle!r}; expected an exact handle like S1"
            )
        path = self._source_handles / f"{source_handle}.json"
        if not path.is_file():
            raise DraftValidationError(
                f"unknown source handle {source_handle!r}; use an exact handle returned by "
                "read_sources"
            )
        document = self._read_handle_document(path, kind="source")
        source_revision_id = document.get("source_revision_id")
        if document.get("handle") != source_handle or not isinstance(source_revision_id, str):
            raise EvidenceIntegrityError(
                phase="evidence",
                code="source_handle_corrupt",
                message=f"stored source handle {source_handle!r} is invalid",
                details={"source_handle": source_handle},
            )
        self.read_revision(source_revision_id)
        return source_revision_id

    def retain_evidence_handle(self, source_revision_id: str, passage_id: str) -> str:
        """Persist one short handle for the exact revision/passage pair."""
        self.resolve_passage(source_revision_id, passage_id)
        existing = self.find_evidence_handle(source_revision_id, passage_id)
        if existing is not None:
            return existing
        handle = f"E{self._next_handle_number(self._evidence_handles, _EVIDENCE_HANDLE)}"
        self._write_handle_document(
            self._evidence_handles / f"{handle}.json",
            {
                "handle": handle,
                "source_revision_id": source_revision_id,
                "passage_id": passage_id,
            },
        )
        return handle

    def find_evidence_handle(self, source_revision_id: str, passage_id: str) -> str | None:
        """Find an existing visible handle without minting a new model-visible reference."""
        for path in sorted(self._evidence_handles.glob("E*.json"), key=_handle_path_order):
            document = self._read_handle_document(path, kind="evidence")
            if (
                document.get("source_revision_id") == source_revision_id
                and document.get("passage_id") == passage_id
            ):
                return str(document["handle"])
        return None

    def resolve_evidence_handle(self, evidence_handle: str) -> tuple[str, str]:
        """Resolve a handle to its exact protected pair, failing closed on typos."""
        if not _EVIDENCE_HANDLE.fullmatch(evidence_handle):
            raise DraftValidationError(
                f"invalid evidence handle {evidence_handle!r}; expected an exact handle like E1"
            )
        path = self._evidence_handles / f"{evidence_handle}.json"
        if not path.is_file():
            raise DraftValidationError(
                f"unknown evidence handle {evidence_handle!r}; use an exact handle returned by "
                "read_sources"
            )
        document = self._read_handle_document(path, kind="evidence")
        source_revision_id = document.get("source_revision_id")
        passage_id = document.get("passage_id")
        if (
            document.get("handle") != evidence_handle
            or not isinstance(source_revision_id, str)
            or not isinstance(passage_id, str)
        ):
            raise EvidenceIntegrityError(
                phase="evidence",
                code="evidence_handle_corrupt",
                message=f"stored evidence handle {evidence_handle!r} is invalid",
                details={"evidence_handle": evidence_handle},
            )
        self.resolve_passage(source_revision_id, passage_id)
        return source_revision_id, passage_id

    def evidence_handles(self) -> tuple[str, ...]:
        """Return exactly the bounded evidence handles already shown to Research."""
        handles: list[str] = []
        for path in sorted(self._evidence_handles.glob("E*.json"), key=_handle_path_order):
            handle = path.stem
            self.resolve_evidence_handle(handle)
            handles.append(handle)
        return tuple(handles)

    @staticmethod
    def _next_handle_number(directory: Path, pattern: re.Pattern[str]) -> int:
        numbers = [
            int(path.stem[1:]) for path in directory.glob("*.json") if pattern.fullmatch(path.stem)
        ]
        return max(numbers, default=0) + 1

    @staticmethod
    def _write_handle_document(path: Path, document: Mapping[str, Any]) -> None:
        if path.exists():
            raise EvidenceIntegrityError(
                phase="evidence",
                code="handle_collision",
                message=f"run-local handle path already exists: {path.name}",
                details={"handle": path.stem},
            )
        path.write_bytes(_canonical_bytes(dict(document)))
        path.chmod(0o444)

    @staticmethod
    def _read_handle_document(path: Path, *, kind: str) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError(
                phase="evidence",
                code=f"{kind}_handle_unreadable",
                message=f"cannot read stored {kind} handle {path.stem!r}",
                details={
                    "handle": path.stem,
                    "original_code": type(exc).__name__,
                    "original_message": str(exc),
                },
            ) from exc
        if not isinstance(document, dict):
            raise EvidenceIntegrityError(
                phase="evidence",
                code=f"{kind}_handle_corrupt",
                message=f"stored {kind} handle {path.stem!r} is not an object",
                details={"handle": path.stem},
            )
        return cast(dict[str, Any], document)

    def _revision_documents(self) -> Iterable[dict[str, Any]]:
        for directory in sorted(self._revisions.glob("source-revision-*")):
            yield self.read_revision(directory.name).to_document()

    @staticmethod
    def _validate_source_id(source_revision_id: str) -> None:
        if not _SOURCE_ID.fullmatch(source_revision_id):
            raise EvidenceIntegrityError(
                phase="evidence",
                code="invalid_source_revision_id",
                message=f"invalid SourceRevision identity {source_revision_id!r}",
                details={"source_revision_id": source_revision_id},
            )

    @staticmethod
    def _integrity(source_revision_id: str, message: str) -> EvidenceIntegrityError:
        return EvidenceIntegrityError(
            phase="evidence",
            code="source_revision_digest_mismatch",
            message=message,
            details={"source_revision_id": source_revision_id},
        )


def sanitize_url(url: str) -> str:
    """Remove userinfo and sensitive query values from any recorded URL."""
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    netloc = f"{hostname}{port}"
    sanitized_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in _SENSITIVE_QUERY_KEYS:
            value = "[REDACTED]"
        sanitized_query.append((key, value))
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(sanitized_query), ""))


class ResearchTools:
    """The two Agent-visible Research tools and their host-owned stages."""

    def __init__(
        self,
        *,
        store: EvidenceStore,
        config: ResearchConfig | None = None,
        budget: ResearchBudget | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.store = store
        self.config = config or ResearchConfig()
        self.budget = budget or ResearchBudget()
        self._search_calls = 0
        self._fetches = 0
        self._bytes = 0
        self._normalized_queries: set[str] = set()
        self._candidate_urls: dict[str, str] = {}
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.config.request_timeout_seconds,
            follow_redirects=True,
            max_redirects=self.config.max_redirects,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": "agent-env-foundry-research/0.1",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search_sources(self, *, queries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Discover candidates through SearXNG; every snippet is non-evidence."""
        candidates: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for position, item in enumerate(queries):
            query = item.get("query")
            focus = item.get("focus")
            if not isinstance(query, str) or not query.strip() or not isinstance(focus, str):
                failures.append(
                    _failure(
                        "search",
                        "invalid_search_request",
                        "each query requires non-empty query and string focus",
                        original_code="invalid_arguments",
                        original_message="invalid query/focus shape",
                        query_index=position,
                    ).to_document()
                )
                continue
            if self._search_calls >= self.budget.max_search_calls:
                failures.append(
                    _failure(
                        "search",
                        "search_budget_exhausted",
                        "search call ceiling exhausted before all requested queries ran",
                        original_code="budget_exhausted",
                        original_message="no search calls remaining",
                        query_index=position,
                        query=query,
                        focus=focus,
                    ).to_document()
                )
                continue
            self._search_calls += 1
            normalized = " ".join(query.casefold().split())
            if normalized in self._normalized_queries:
                warnings.append(
                    {
                        "code": "normalized_query_duplicate",
                        "message": (
                            "query normalizes to an earlier query; execution was not blocked"
                        ),
                        "query": query,
                        "focus": focus,
                    }
                )
            self._normalized_queries.add(normalized)
            requested_at = _utc_now()
            receipt_handle = f"Q{self._search_calls}"
            receipt: dict[str, Any] = {
                "receipt_handle": receipt_handle,
                "query": query,
                "focus": focus,
                "requested_at": requested_at,
                "normalized_query_warning": normalized in self._normalized_queries
                and any(warning["query"] == query for warning in warnings),
            }
            try:
                response = self._client.get(
                    f"{self.config.searxng_url.rstrip('/')}/search",
                    params={"q": query, "format": "json"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    raise ValueError("SearXNG response does not contain a results array")
                receipt["status_code"] = response.status_code
                receipts.append(receipt)
                for rank, raw in enumerate(
                    payload["results"][: self.config.max_results_per_query], start=1
                ):
                    if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
                        failures.append(
                            _failure(
                                "search",
                                "invalid_search_result",
                                "SearXNG result omitted a URL",
                                original_code="invalid_result",
                                original_message="result is not an object with a URL",
                                receipt_handle=receipt_handle,
                                rank=rank,
                            ).to_document()
                        )
                        continue
                    raw_url = raw["url"]
                    candidate_handle = f"C{len(self._candidate_urls) + 1}"
                    self._candidate_urls[candidate_handle] = raw_url
                    candidates.append(
                        {
                            "candidate_handle": candidate_handle,
                            "receipt_handle": receipt_handle,
                            "rank": rank,
                            "url": sanitize_url(raw_url),
                            "title": str(raw.get("title") or ""),
                            "snippet": str(raw.get("content") or ""),
                            "query": query,
                            "focus": focus,
                            "discovery_only": True,
                        }
                    )
            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                receipts.append(receipt)
                failures.append(
                    _failure(
                        "search",
                        "searxng_request_failed",
                        "SearXNG discovery failed; no alternate route was used",
                        original_code=type(exc).__name__,
                        original_message=_safe_exception_message(exc),
                        receipt_handle=receipt_handle,
                        query=query,
                        focus=focus,
                    ).to_document()
                )
        return {
            "candidates": candidates,
            "receipts": receipts,
            "failures": failures,
            "warnings": warnings,
            "remaining_budget": self._remaining_budget(),
        }

    def read_sources(self, *, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Fetch only Agent-selected sources, projecting each with its own focus."""
        reads: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
            return {
                "reads": [],
                "failures": [
                    _failure(
                        "selection",
                        "invalid_read_entries",
                        "read_sources requires at least one {source, focus} entry",
                        original_code="invalid_arguments",
                        original_message="entries is empty or not an array",
                    ).to_document()
                ],
                "remaining_budget": self._remaining_budget(),
            }
        for entry_index, entry in enumerate(entries):
            source_handle: str | None = None
            selector: Any = None
            try:
                if not isinstance(entry, Mapping):
                    raise _failure(
                        "selection",
                        "invalid_read_entry",
                        "each read entry must be an object with source and focus",
                        original_code="invalid_arguments",
                        original_message=type(entry).__name__,
                    )
                selector = entry.get("source")
                focus = entry.get("focus")
                if not isinstance(selector, str) or not selector:
                    raise _failure(
                        "selection",
                        "invalid_read_entry",
                        "each read entry requires a non-empty source selector",
                        original_code="invalid_arguments",
                        original_message="empty or non-string source",
                    )
                if not isinstance(focus, str) or not focus.strip():
                    raise _failure(
                        "selection",
                        "invalid_read_entry",
                        "each read entry requires a non-empty Agent-authored focus",
                        original_code="invalid_arguments",
                        original_message="empty or non-string focus",
                    )
                if _SOURCE_ID.fullmatch(selector):
                    raise _failure(
                        "selection",
                        "protected_source_id_not_allowed",
                        "read_sources accepts the short source handle, not a protected revision ID",
                        original_code="protected_reference",
                        original_message="use the exact S-number returned by read_sources",
                    )
                selection_kind = "url"
                if _SOURCE_HANDLE.fullmatch(selector):
                    try:
                        source_revision_id = self.store.resolve_source_handle(selector)
                    except DraftValidationError as exc:
                        raise _failure(
                            "selection",
                            "unknown_source_handle",
                            str(exc),
                            original_code="unknown_handle",
                            original_message=selector,
                        ) from exc
                    revision = self.store.read_revision(source_revision_id)
                    source_handle = selector
                    selection_kind = "source"
                else:
                    raw_url = self._candidate_urls.get(selector)
                    selection_kind = "candidate" if raw_url is not None else "url"
                    if raw_url is None:
                        if selector.startswith("C"):
                            raise _failure(
                                "selection",
                                "unknown_candidate_handle",
                                "candidate handle was not returned by this Research run",
                                original_code="unknown_candidate",
                                original_message=selector,
                            )
                        raw_url = selector
                    revision = self._fetch(raw_url)
                if source_handle is None:
                    source_handle = self.store.retain_source_handle(revision.source_revision_id)
                extraction = self._extract(revision)
                projected, focus_result = _project_passages(
                    cast(list[dict[str, Any]], extraction["passages"]),
                    focus=focus.strip(),
                    max_passages=self.config.max_passages_per_read,
                )
                projected_passages: list[dict[str, Any]] = []
                visible_count = len(self.store.evidence_handles())
                for passage in projected:
                    passage_id = str(passage["passage_id"])
                    evidence_handle = self.store.find_evidence_handle(
                        revision.source_revision_id,
                        passage_id,
                    )
                    if evidence_handle is None:
                        if visible_count >= self.config.max_visible_passages_per_run:
                            continue
                        evidence_handle = self.store.retain_evidence_handle(
                            revision.source_revision_id,
                            passage_id,
                        )
                        visible_count += 1
                    projected_passages.append(
                        {
                            "evidence_handle": evidence_handle,
                            "text": str(passage["text"]),
                            "occurrence_count": len(
                                cast(list[dict[str, Any]], passage["occurrences"])
                            ),
                        }
                    )
                if len(projected_passages) < len(projected):
                    focus_result["returned_passage_count"] = len(projected_passages)
                    focus_result["truncated"] = True
                    if not projected_passages:
                        focus_result["status"] = "run_limit_reached"
                reads.append(
                    {
                        "selection": sanitize_url(selector),
                        "selection_kind": selection_kind,
                        "source_handle": source_handle,
                        "final_url": revision.final_url,
                        "media_type": revision.media_type,
                        "focus": focus.strip(),
                        "focus_result": focus_result,
                        "passages": projected_passages,
                    }
                )
            except ResearchFailure as exc:
                document = _model_failure_document(exc, source_handle=source_handle)
                document["details"]["entry_index"] = entry_index
                if isinstance(selector, str) and _SOURCE_ID.fullmatch(selector):
                    document["details"]["selection"] = "[PROTECTED_SOURCE_ID]"
                elif isinstance(selector, str):
                    document["details"]["selection"] = sanitize_url(selector)
                else:
                    document["details"]["selection"] = ""
                if "original_code" not in document["details"]:
                    document["details"]["original_code"] = exc.code
                if "original_message" not in document["details"]:
                    document["details"]["original_message"] = exc.message
                failures.append(document)
        return {
            "reads": reads,
            "failures": failures,
            "remaining_budget": self._remaining_budget(),
        }

    def _fetch(self, raw_url: str) -> SourceRevision:
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _failure(
                "fetch",
                "unsupported_url",
                "read_sources accepts only absolute http(s) URLs",
                original_code="invalid_url",
                original_message=sanitize_url(raw_url),
            )
        if self._fetches >= self.budget.max_fetches:
            raise _failure(
                "fetch",
                "fetch_budget_exhausted",
                "fetch ceiling exhausted; no substitute source was searched",
                original_code="budget_exhausted",
                original_message="no fetches remaining",
            )
        self._fetches += 1
        try:
            with self._client.stream("GET", raw_url) as response:
                chunks: list[bytes] = []
                byte_count = 0
                for chunk in response.iter_raw():
                    byte_count += len(chunk)
                    projected_total = self._bytes + len(chunk)
                    if projected_total > self.budget.max_total_bytes:
                        # The chunk has already crossed the HTTP boundary. Mark
                        # the safety ceiling exhausted even though no partial
                        # SourceRevision will be retained.
                        self._bytes = self.budget.max_total_bytes
                        raise _failure(
                            "fetch",
                            "total_byte_budget_exhausted",
                            "run byte ceiling exhausted while reading selected source",
                            original_code="budget_exhausted",
                            original_message=str(projected_total),
                            max_total_bytes=self.budget.max_total_bytes,
                        )
                    self._bytes = projected_total
                    if byte_count > self.config.max_bytes_per_source:
                        raise _failure(
                            "fetch",
                            "source_byte_limit_exceeded",
                            "source exceeded its exact-byte ceiling",
                            original_code="byte_limit_exceeded",
                            original_message=str(byte_count),
                            max_bytes=self.config.max_bytes_per_source,
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
                media_type, charset = _parse_content_type(content_type)
                redirects = tuple(
                    {
                        "url": sanitize_url(str(hop.request.url)),
                        "status_code": hop.status_code,
                        "location": sanitize_url(hop.headers.get("location", "")),
                    }
                    for hop in response.history
                )
                revision = self.store.retain_revision(
                    body=body,
                    metadata={
                        "requested_url": sanitize_url(raw_url),
                        "final_url": sanitize_url(str(response.url)),
                        "redirect_chain": list(redirects),
                        "status_code": response.status_code,
                        "media_type": media_type,
                        "content_type": content_type,
                        "charset": charset,
                        "content_encoding": response.headers.get("content-encoding", ""),
                        "retrieved_at": _utc_now(),
                    },
                )
                if not 200 <= response.status_code < 300:
                    raise _failure(
                        "fetch",
                        "http_status_failure",
                        "selected source returned a non-success HTTP status",
                        original_code=response.status_code,
                        original_message=response.reason_phrase,
                        source_revision_id=revision.source_revision_id,
                    )
                return revision
        except ResearchFailure:
            raise
        except httpx.HTTPError as exc:
            raise _failure(
                "fetch",
                "http_request_failed",
                "selected source retrieval failed; no substitute was searched",
                original_code=type(exc).__name__,
                original_message=_safe_exception_message(exc),
                requested_url=sanitize_url(raw_url),
            ) from exc

    def _extract(self, revision: SourceRevision) -> dict[str, Any]:
        if revision.media_type not in {"text/html", "application/xhtml+xml"}:
            raise _failure(
                "extract",
                "unsupported_media_type",
                f"media type {revision.media_type!r} is not supported by Slice 2 Extract",
                original_code="unsupported_media_type",
                original_message=revision.media_type or "missing content type",
                source_revision_id=revision.source_revision_id,
            )
        if revision.content_encoding.casefold() not in {"", "identity"}:
            raise _failure(
                "extract",
                "unsupported_content_encoding",
                "retained raw bytes use an unsupported HTTP content encoding",
                original_code="unsupported_content_encoding",
                original_message=revision.content_encoding,
                source_revision_id=revision.source_revision_id,
            )
        try:
            codecs.lookup(revision.charset)
            decoded = revision.body.decode(revision.charset, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise _failure(
                "extract",
                "source_decode_failed",
                "retained source bytes could not be decoded with the recorded charset",
                original_code=type(exc).__name__,
                original_message=str(exc),
                source_revision_id=revision.source_revision_id,
                charset=revision.charset,
            ) from exc
        installed_version = importlib.metadata.version("crawl4ai")
        if installed_version != _CRAWL4AI_VERSION:
            raise _failure(
                "extract",
                "crawl4ai_version_mismatch",
                "Extract runtime does not match the pinned compatible Crawl4AI version",
                original_code="version_mismatch",
                original_message=installed_version,
                expected_version=_CRAWL4AI_VERSION,
            )
        options: dict[str, Any] = {
            "strategy": "LXMLWebScrapingStrategy.scrap",
            "word_count_threshold": 1,
            "excluded_tags": [
                "nav",
                "header",
                "footer",
                "aside",
                "script",
                "style",
                "noscript",
            ],
            "exclude_external_images": True,
            "markdown": {
                "generator": "DefaultMarkdownGenerator",
                "body_width": 0,
                "citations": False,
            },
        }
        try:
            scraped = LXMLWebScrapingStrategy().scrap(
                revision.final_url,
                decoded,
                word_count_threshold=options["word_count_threshold"],
                excluded_tags=options["excluded_tags"],
                exclude_external_images=options["exclude_external_images"],
            )
            if not scraped.success:
                raise ValueError("Crawl4AI scraping strategy returned success=false")
            generated = DefaultMarkdownGenerator(options={"body_width": 0}).generate_markdown(
                scraped.cleaned_html,
                base_url=revision.final_url,
                citations=False,
            )
            markdown = generated.raw_markdown
            if not isinstance(markdown, str):
                raise TypeError("Crawl4AI markdown output is not text")
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _failure(
                "extract",
                "crawl4ai_extract_failed",
                "Crawl4AI failed against the retained source bytes",
                original_code=type(exc).__name__,
                original_message=str(exc),
                source_revision_id=revision.source_revision_id,
            ) from exc
        passages = _passages_from_markdown(
            markdown,
            source_revision_id=revision.source_revision_id,
            max_characters=self.config.max_passage_characters,
        )
        derivation = {
            "source_revision_id": revision.source_revision_id,
            "source_body_digest": revision.body_digest,
            "decoder": {"charset": revision.charset, "errors": "strict"},
            "crawl4ai": {"version": installed_version, "options": options},
            "markdown_digest": _sha256(markdown.encode("utf-8")),
            "passages": passages,
        }
        output_digest = _sha256(_canonical_bytes(derivation))
        return self.store.retain_extraction({**derivation, "output_digest": output_digest})

    def _remaining_budget(self) -> dict[str, int]:
        return {
            "search_calls": max(0, self.budget.max_search_calls - self._search_calls),
            "fetches": max(0, self.budget.max_fetches - self._fetches),
            "bytes": max(0, self.budget.max_total_bytes - self._bytes),
        }


def _safe_exception_message(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} {exc.response.reason_phrase}"
    if isinstance(exc, httpx.RequestError):
        return type(exc).__name__
    return str(exc)


_PROTECTED_ID_TEXT = re.compile(
    r"(?:source-revision|extraction|passage)-[0-9a-f]{64}|"
    r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"
)


def _model_failure_document(
    failure: ResearchFailure, *, source_handle: str | None
) -> dict[str, Any]:
    """Project a typed failure without leaking protected evidence identities."""
    document = failure.to_document()
    details = cast(dict[str, Any], document["details"])
    for key in ("source_revision_id", "extraction_id", "passage_id", "body_digest"):
        details.pop(key, None)
    if source_handle is not None:
        details["source_handle"] = source_handle

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return _PROTECTED_ID_TEXT.sub("[PROTECTED_ID]", value)
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value

    return cast(dict[str, Any], redact(document))


def _parse_content_type(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split(";")]
    media_type = parts[0].casefold() if parts and parts[0] else ""
    charset = "utf-8"
    for parameter in parts[1:]:
        name, separator, raw = parameter.partition("=")
        if separator and name.strip().casefold() == "charset":
            charset = raw.strip().strip('"').casefold()
    return media_type, charset


def _passages_from_markdown(
    markdown: str,
    *,
    source_revision_id: str,
    max_characters: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    offset = 0
    line_number = 0
    for raw_line in markdown.splitlines(keepends=True):
        line_number += 1
        content = raw_line.rstrip("\r\n")
        leading = len(content) - len(content.lstrip())
        text = content.strip()
        line_start = offset + leading
        offset += len(raw_line)
        if not text or text.startswith("#"):
            continue
        for chunk_start, chunk in _bounded_chunks(text, max_characters):
            start = line_start + chunk_start
            end = start + len(chunk)
            digest = _sha256(chunk.encode("utf-8"))
            occurrence = {
                "locator": f"extracted://{source_revision_id}#chars={start}-{end}",
                "start_character": start,
                "end_character": end,
                "start_line": line_number,
                "end_line": line_number,
                "text_digest": digest,
            }
            existing = grouped.get(chunk)
            if existing is None:
                grouped[chunk] = {
                    "passage_id": f"passage-{digest}",
                    "text": chunk,
                    "text_digest": digest,
                    "occurrences": [occurrence],
                }
            else:
                cast(list[dict[str, Any]], existing["occurrences"]).append(occurrence)
    return list(grouped.values())


def _project_passages(
    passages: Sequence[dict[str, Any]],
    *,
    focus: str,
    max_passages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select an exact bounded view using only deterministic lexical overlap."""
    focus_terms = frozenset(re.findall(r"\w+", focus.casefold()))
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for position, passage in enumerate(passages):
        passage_terms = frozenset(re.findall(r"\w+", str(passage["text"]).casefold()))
        overlap = len(focus_terms.intersection(passage_terms))
        if overlap:
            ranked.append((-overlap, position, passage))
    ranked.sort(key=lambda item: (item[0], item[1]))
    matched_passage_count = len(ranked)
    selected = [item[2] for item in ranked[:max_passages]]
    status = "matched" if selected else "no_match"
    if matched_passage_count and max_passages == 0:
        status = "run_limit_reached"
    return selected, {
        "status": status,
        "matched_passage_count": matched_passage_count,
        "returned_passage_count": len(selected),
        "truncated": matched_passage_count > len(selected),
    }


def _bounded_chunks(text: str, limit: int) -> Iterable[tuple[int, str]]:
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + limit)
        if end < len(text):
            boundary = text.rfind(" ", cursor, end)
            if boundary > cursor:
                end = boundary
        chunk = text[cursor:end].strip()
        if chunk:
            leading = len(text[cursor:end]) - len(text[cursor:end].lstrip())
            yield cursor + leading, chunk
        cursor = end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1


@dataclass(frozen=True)
class NeedClause:
    clause_id: str
    text: str

    def to_document(self) -> dict[str, str]:
        return {"clause_id": self.clause_id, "text": self.text}


@dataclass(frozen=True)
class NeedRecord:
    original_need: str
    clauses: tuple[NeedClause, ...]

    @classmethod
    def from_clauses(cls, original_need: str, clauses: Sequence[str]) -> NeedRecord:
        cleaned = tuple(item.strip() for item in clauses if item.strip())
        if not original_need.strip() or not cleaned:
            raise ValueError("Need and at least one atomic clause are required")
        return cls(
            original_need=original_need,
            clauses=tuple(
                NeedClause(f"NEED-{index:03d}", text) for index, text in enumerate(cleaned, start=1)
            ),
        )

    @classmethod
    def from_text(cls, original_need: str) -> NeedRecord:
        parts: list[str] = []
        for raw_line in re.split(r"(?:\r?\n)+", original_need):
            line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", raw_line.strip())
            for raw_clause in re.split(r"(?<=[.!?;])\s+", line):
                text = raw_clause.strip()
                if text:
                    parts.append(text)
        return cls.from_clauses(original_need, parts)

    def to_document(self) -> dict[str, Any]:
        return {
            "original_need": self.original_need,
            "clauses": [item.to_document() for item in self.clauses],
        }


_EVIDENCE_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_handle": {"type": "string"},
    },
    "required": ["evidence_handle"],
    "additionalProperties": False,
}
_REQUIREMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "draft_id": {"type": "string"},
        "basis": {"type": "string", "enum": ["need", "external_evidence"]},
        "statement": {"type": "string"},
        "observable": {"type": "string"},
        "falsifiable_consequence": {"type": "string"},
        "evidence": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
    },
    "required": [
        "draft_id",
        "basis",
        "statement",
        "observable",
        "falsifiable_consequence",
        "evidence",
    ],
    "additionalProperties": False,
}
_WORKFLOW_REQUIREMENT_SCHEMA: dict[str, Any] = {
    **_REQUIREMENT_SCHEMA,
    "properties": {
        **_REQUIREMENT_SCHEMA["properties"],
        "precondition": {"type": "string"},
        "postcondition": {"type": "string"},
    },
    "required": [
        *_REQUIREMENT_SCHEMA["required"],
        "precondition",
        "postcondition",
    ],
}
_REFUSAL_REQUIREMENT_SCHEMA: dict[str, Any] = {
    **_REQUIREMENT_SCHEMA,
    "properties": {
        **_REQUIREMENT_SCHEMA["properties"],
        "refusal_condition": {"type": "string"},
        "prohibited_mutation": {"type": "string"},
    },
    "required": [
        *_REQUIREMENT_SCHEMA["required"],
        "refusal_condition",
        "prohibited_mutation",
    ],
}
RESEARCH_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selected_interpretation": {"type": "string"},
        "need_mapping": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {"type": "string"},
                    "disposition": {
                        "type": "string",
                        "enum": ["accepted", "unsupported"],
                    },
                    "requirement_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["clause_id", "disposition", "requirement_refs", "rationale"],
                "additionalProperties": False,
            },
        },
        "capabilities": {"type": "array", "items": _REQUIREMENT_SCHEMA},
        "workflows": {"type": "array", "items": _WORKFLOW_REQUIREMENT_SCHEMA},
        "invariants": {"type": "array", "items": _REQUIREMENT_SCHEMA},
        "refusals": {"type": "array", "items": _REFUSAL_REQUIREMENT_SCHEMA},
        "initial_world": {"type": "array", "items": _REQUIREMENT_SCHEMA},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "exclusions": {"type": "array", "items": {"type": "string"}},
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "resolution": {"type": "string"},
                    "evidence": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
                },
                "required": ["topic", "resolution", "evidence"],
                "additionalProperties": False,
            },
        },
        "open_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {"type": "string"},
                    "description": {"type": "string"},
                    "can_change_core_requirement": {"type": "boolean"},
                },
                "required": ["clause_id", "description", "can_change_core_requirement"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "selected_interpretation",
        "need_mapping",
        *_REQUIREMENT_SECTIONS,
        "assumptions",
        "alternatives",
        "exclusions",
        "contradictions",
        "open_gaps",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class EvidenceIndexEntry:
    evidence_handle: str
    source_handle: str
    source_revision_id: str
    body_digest: str
    final_url: str
    passage_id: str
    passage_digest: str
    text: str
    locators: tuple[str, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "evidence_handle": self.evidence_handle,
            "source_handle": self.source_handle,
            "source_revision_id": self.source_revision_id,
            "body_digest": self.body_digest,
            "final_url": self.final_url,
            "passage_id": self.passage_id,
            "passage_digest": self.passage_digest,
            "text": self.text,
            "locators": list(self.locators),
        }


@dataclass(frozen=True)
class EvidenceIndex:
    entries: tuple[EvidenceIndexEntry, ...]

    def to_document(self) -> dict[str, Any]:
        return {"entries": [entry.to_document() for entry in self.entries]}

    def to_markdown(self) -> str:
        lines = ["## Evidence Index", ""]
        if not self.entries:
            return "\n".join([*lines, "No cited passages."])
        for entry in self.entries:
            lines.extend(
                [
                    (
                        f"- `{entry.evidence_handle}` / `{entry.source_handle}` — passage "
                        f"`{entry.passage_id}` — SourceRevision `{entry.source_revision_id}`"
                    ),
                    f"  - URL: {entry.final_url}",
                    f"  - Body SHA-256: `{entry.body_digest}`",
                    f"  - Passage SHA-256: `{entry.passage_digest}`",
                    f"  - Locators: {', '.join(f'`{item}`' for item in entry.locators)}",
                    f"  - Passage: {entry.text}",
                ]
            )
        return "\n".join(lines)

    def to_model_markdown(self) -> str:
        """Render only bounded short handles and passages for a model turn."""
        lines = ["## Bounded Evidence", ""]
        if not self.entries:
            return "\n".join([*lines, "No external passages were cited."])
        for entry in self.entries:
            lines.extend(
                [
                    f"- Evidence `{entry.evidence_handle}` from source `{entry.source_handle}`",
                    f"  - URL: {entry.final_url}",
                    f"  - Exact extracted passage: {entry.text}",
                ]
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class BriefRequirement:
    requirement_id: str
    category: str
    draft_id: str
    basis: Literal["need", "external_evidence"] | str
    statement: str
    observable: str
    falsifiable_consequence: str
    evidence: tuple[dict[str, str], ...]
    precondition: str | None = None
    postcondition: str | None = None
    refusal_condition: str | None = None
    prohibited_mutation: str | None = None

    def to_document(self) -> dict[str, Any]:
        document = {
            "requirement_id": self.requirement_id,
            "category": self.category,
            "draft_id": self.draft_id,
            "basis": self.basis,
            "statement": self.statement,
            "observable": self.observable,
            "falsifiable_consequence": self.falsifiable_consequence,
            "evidence": [dict(item) for item in self.evidence],
        }
        for field_name in (
            "precondition",
            "postcondition",
            "refusal_condition",
            "prohibited_mutation",
        ):
            value = getattr(self, field_name)
            if value is not None:
                document[field_name] = value
        return document


@dataclass(frozen=True)
class DevelopmentBrief:
    markdown: str
    evidence_index: EvidenceIndex
    review_evidence_index: EvidenceIndex
    requirements: tuple[BriefRequirement, ...]
    need: dict[str, Any]
    draft: dict[str, Any]
    digest: str

    def to_document(self) -> dict[str, Any]:
        return {
            "need": _json_copy(self.need),
            "requirements": [item.to_document() for item in self.requirements],
            "evidence_index": self.evidence_index.to_document(),
            "review_evidence_index": self.review_evidence_index.to_document(),
            "markdown": self.markdown,
            "digest": self.digest,
        }

    def to_model_document(self) -> dict[str, Any]:
        """Project Brief semantics without protected hashes or host audit prose."""
        requirements = []
        for requirement in self.requirements:
            projected = {
                "requirement_id": requirement.requirement_id,
                "draft_id": requirement.draft_id,
                "category": requirement.category,
                "basis": requirement.basis,
                "statement": requirement.statement,
                "observable": requirement.observable,
                "falsifiable_consequence": requirement.falsifiable_consequence,
                "evidence": [
                    {"evidence_handle": str(reference["evidence_handle"])}
                    for reference in requirement.evidence
                ],
            }
            for field_name in (
                "precondition",
                "postcondition",
                "refusal_condition",
                "prohibited_mutation",
            ):
                value = getattr(requirement, field_name)
                if value is not None:
                    projected[field_name] = value
            requirements.append(projected)
        return {
            "selected_interpretation": self.draft.get("selected_interpretation", "test"),
            "need_mapping": _json_copy(self.draft.get("need_mapping", [])),
            "requirements": requirements,
            "assumptions": _json_copy(self.draft.get("assumptions", [])),
            "alternatives": _json_copy(self.draft.get("alternatives", [])),
            "exclusions": _json_copy(self.draft.get("exclusions", [])),
            "contradictions": _json_copy(self.draft.get("contradictions", [])),
            "open_gaps": _json_copy(self.draft.get("open_gaps", [])),
        }

    @classmethod
    def for_test(
        cls,
        *,
        markdown: str,
        evidence_index: EvidenceIndex,
        requirement_ids: Sequence[str],
    ) -> DevelopmentBrief:
        requirements = tuple(
            BriefRequirement(item, "test", item, "need", item, item, item, ())
            for item in requirement_ids
        )
        clauses = [
            {"clause_id": f"NEED-{index:03d}", "text": requirement_id}
            for index, requirement_id in enumerate(requirement_ids, start=1)
        ]
        draft = {
            "selected_interpretation": "test",
            "need_mapping": [
                {
                    "clause_id": clause["clause_id"],
                    "disposition": "accepted",
                    "requirement_refs": [requirement_id],
                    "rationale": "test",
                }
                for clause, requirement_id in zip(clauses, requirement_ids, strict=True)
            ],
            "assumptions": [],
            "alternatives": [],
            "exclusions": [],
            "contradictions": [],
            "open_gaps": [],
        }
        preimage = {
            "need": {"original_need": "test", "clauses": clauses},
            "requirements": [item.to_document() for item in requirements],
            "evidence_index": evidence_index.to_document(),
            "markdown": markdown,
        }
        return cls(
            markdown=markdown,
            evidence_index=evidence_index,
            review_evidence_index=evidence_index,
            requirements=requirements,
            need=cast(dict[str, Any], preimage["need"]),
            draft=draft,
            digest=_sha256(_canonical_bytes(preimage)),
        )


@dataclass(frozen=True)
class BuilderProjection:
    """The sole deeply immutable Research-derived input to Builder and Qualifier."""

    frozen_need: Mapping[str, Any]
    selected_world: Mapping[str, Any]
    requirements: tuple[Mapping[str, Any], ...]
    initial_world_relations: tuple[Mapping[str, Any], ...]
    cited_evidence: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frozen_need", _freeze_json(self.frozen_need))
        object.__setattr__(self, "selected_world", _freeze_json(self.selected_world))
        object.__setattr__(
            self,
            "requirements",
            tuple(_freeze_json(item) for item in self.requirements),
        )
        object.__setattr__(
            self,
            "initial_world_relations",
            tuple(_freeze_json(item) for item in self.initial_world_relations),
        )
        object.__setattr__(
            self,
            "cited_evidence",
            tuple(_freeze_json(item) for item in self.cited_evidence),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "frozen_need": _thaw_json(self.frozen_need),
            "selected_world": _thaw_json(self.selected_world),
            "requirements": _thaw_json(self.requirements),
            "initial_world_relations": _thaw_json(self.initial_world_relations),
            "cited_evidence": _thaw_json(self.cited_evidence),
        }


def _validate_research_draft_semantics(document: Mapping[str, Any]) -> None:
    """Enforce compact content constraints omitted from provider-facing schemas."""

    def nonempty(value: Any, path: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise DraftValidationError(f"Research Draft field {path} must be a non-empty string")

    nonempty(document["selected_interpretation"], "selected_interpretation")
    for index, mapping in enumerate(cast(list[dict[str, Any]], document["need_mapping"])):
        nonempty(mapping["clause_id"], f"need_mapping[{index}].clause_id")
        nonempty(mapping["rationale"], f"need_mapping[{index}].rationale")
        for ref_index, requirement_ref in enumerate(cast(list[str], mapping["requirement_refs"])):
            nonempty(requirement_ref, f"need_mapping[{index}].requirement_refs[{ref_index}]")
    for section in _REQUIREMENT_SECTIONS:
        for index, requirement in enumerate(cast(list[dict[str, Any]], document[section])):
            for field_name in (
                "draft_id",
                "statement",
                "observable",
                "falsifiable_consequence",
            ):
                nonempty(requirement[field_name], f"{section}[{index}].{field_name}")
            for ref_index, evidence_ref in enumerate(
                cast(list[dict[str, Any]], requirement["evidence"])
            ):
                nonempty(
                    evidence_ref["evidence_handle"],
                    f"{section}[{index}].evidence[{ref_index}].evidence_handle",
                )
            if section == "workflows":
                nonempty(requirement["precondition"], f"workflows[{index}].precondition")
                nonempty(requirement["postcondition"], f"workflows[{index}].postcondition")
            if section == "refusals":
                nonempty(
                    requirement["refusal_condition"],
                    f"refusals[{index}].refusal_condition",
                )
                nonempty(
                    requirement["prohibited_mutation"],
                    f"refusals[{index}].prohibited_mutation",
                )
    for field_name in ("assumptions", "alternatives", "exclusions"):
        for index, value in enumerate(cast(list[str], document[field_name])):
            nonempty(value, f"{field_name}[{index}]")
    for index, contradiction in enumerate(cast(list[dict[str, Any]], document["contradictions"])):
        nonempty(contradiction["topic"], f"contradictions[{index}].topic")
        nonempty(contradiction["resolution"], f"contradictions[{index}].resolution")
        for ref_index, contradiction_ref in enumerate(
            cast(list[dict[str, Any]], contradiction["evidence"])
        ):
            nonempty(
                contradiction_ref["evidence_handle"],
                f"contradictions[{index}].evidence[{ref_index}].evidence_handle",
            )
    for index, gap in enumerate(cast(list[dict[str, Any]], document["open_gaps"])):
        nonempty(gap["clause_id"], f"open_gaps[{index}].clause_id")
        nonempty(gap["description"], f"open_gaps[{index}].description")


def _reject_raw_model_identifiers(document: Any) -> None:
    for text in _walk_strings(document):
        if _PROTECTED_ID_TEXT.search(text):
            raise DraftValidationError(
                "Research Draft contains a raw 64-hex identifier; use the exact short handle "
                "returned by the host"
            )


def _evidence_index_entry(store: EvidenceStore, evidence_handle: str) -> EvidenceIndexEntry:
    source_revision_id, passage_id = store.resolve_evidence_handle(evidence_handle)
    revision, _extraction, passage = store.resolve_passage(source_revision_id, passage_id)
    source_handle = store.retain_source_handle(source_revision_id)
    return EvidenceIndexEntry(
        evidence_handle=evidence_handle,
        source_handle=source_handle,
        source_revision_id=revision.source_revision_id,
        body_digest=revision.body_digest,
        final_url=revision.final_url,
        passage_id=str(passage["passage_id"]),
        passage_digest=str(passage["text_digest"]),
        text=str(passage["text"]),
        locators=tuple(
            str(item["locator"]) for item in cast(list[dict[str, Any]], passage["occurrences"])
        ),
    )


def derive_development_brief(
    *, need: NeedRecord, draft: Mapping[str, Any], store: EvidenceStore
) -> DevelopmentBrief:
    """Validate evidence closure, assign stable IDs, and render the Brief."""
    document = _json_copy(dict(draft))
    errors = sorted(Draft202012Validator(RESEARCH_DRAFT_SCHEMA).iter_errors(document), key=str)
    if errors:
        error = errors[0]
        location = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        raise DraftValidationError(
            f"Research Draft schema/evidence contract failed at {location}: {error.message}; "
            "external citations must use an exact evidence handle returned by read_sources"
        )
    _validate_research_draft_semantics(document)
    _reject_downstream_prescriptions(document)
    _reject_raw_model_identifiers(document)
    expected_clause_ids = [item.clause_id for item in need.clauses]
    mappings = cast(list[dict[str, Any]], document["need_mapping"])
    actual_clause_ids = [str(item["clause_id"]) for item in mappings]
    if actual_clause_ids != expected_clause_ids:
        raise DraftValidationError(
            "atomic Need coverage mismatch: expected exactly "
            f"{expected_clause_ids}, got {actual_clause_ids}"
        )
    requirements: list[BriefRequirement] = []
    draft_id_to_requirement: dict[str, str] = {}
    evidence_entries: dict[str, EvidenceIndexEntry] = {}
    for section in _REQUIREMENT_SECTIONS:
        for raw in cast(list[dict[str, Any]], document[section]):
            draft_id = str(raw["draft_id"])
            if draft_id in draft_id_to_requirement:
                raise DraftValidationError(f"duplicate requirement draft_id {draft_id!r}")
            requirement_id = f"REQ-{len(requirements) + 1:03d}"
            draft_id_to_requirement[draft_id] = requirement_id
            evidence: list[dict[str, str]] = []
            basis = str(raw["basis"])
            raw_evidence = cast(list[dict[str, str]], raw["evidence"])
            if basis == "external_evidence" and not raw_evidence:
                raise DraftValidationError(
                    f"external_evidence requirement {draft_id!r} requires at least one "
                    "resolvable evidence handle"
                )
            if basis == "need" and raw_evidence:
                raise DraftValidationError(
                    f"need-basis requirement {draft_id!r} must contain zero evidence handles"
                )
            handles = [reference["evidence_handle"] for reference in raw_evidence]
            if len(handles) != len(set(handles)):
                raise DraftValidationError(
                    f"requirement {draft_id!r} contains duplicate evidence handles"
                )
            for reference in raw_evidence:
                entry = _evidence_index_entry(store, reference["evidence_handle"])
                evidence_entries[entry.evidence_handle] = entry
                evidence.append(
                    {
                        "evidence_handle": entry.evidence_handle,
                        "source_handle": entry.source_handle,
                        "source_revision_id": entry.source_revision_id,
                        "passage_id": entry.passage_id,
                    }
                )
            requirements.append(
                BriefRequirement(
                    requirement_id=requirement_id,
                    category=section,
                    draft_id=draft_id,
                    basis=basis,
                    statement=str(raw["statement"]),
                    observable=str(raw["observable"]),
                    falsifiable_consequence=str(raw["falsifiable_consequence"]),
                    evidence=tuple(evidence),
                    precondition=(str(raw["precondition"]) if section == "workflows" else None),
                    postcondition=(str(raw["postcondition"]) if section == "workflows" else None),
                    refusal_condition=(
                        str(raw["refusal_condition"]) if section == "refusals" else None
                    ),
                    prohibited_mutation=(
                        str(raw["prohibited_mutation"]) if section == "refusals" else None
                    ),
                )
            )
    used_refs: set[str] = set()
    for mapping in mappings:
        refs = cast(list[str], mapping["requirement_refs"])
        if len(refs) != len(set(refs)):
            raise DraftValidationError(
                f"Need clause {mapping['clause_id']} contains duplicate requirement references"
            )
        if mapping["disposition"] == "unsupported" and refs:
            raise DraftValidationError(
                f"unsupported Need mapping {mapping['clause_id']} must have no requirement "
                "references"
            )
        if mapping["disposition"] == "accepted" and not refs:
            raise DraftValidationError(
                f"accepted Need clause {mapping['clause_id']} has no requirement references"
            )
        unknown = sorted(set(refs) - set(draft_id_to_requirement))
        if unknown:
            raise DraftValidationError(
                f"Need clause {mapping['clause_id']} references unknown requirements {unknown}"
            )
        used_refs.update(refs)
    orphaned = sorted(set(draft_id_to_requirement) - used_refs)
    if orphaned:
        raise DraftValidationError(f"requirements are not mapped to a Need clause: {orphaned}")
    for contradiction in cast(list[dict[str, Any]], document["contradictions"]):
        references = cast(list[dict[str, str]], contradiction["evidence"])
        if len(references) < 2:
            raise DraftValidationError(
                f"contradiction {contradiction['topic']!r} requires at least two evidence handles"
            )
        for reference in references:
            entry = _evidence_index_entry(store, reference["evidence_handle"])
            evidence_entries[entry.evidence_handle] = entry
    evidence_index = EvidenceIndex(entries=tuple(evidence_entries.values()))
    review_evidence_index = EvidenceIndex(
        entries=tuple(
            _evidence_index_entry(store, evidence_handle)
            for evidence_handle in store.evidence_handles()
        )
    )
    markdown = _render_brief(
        need=need,
        draft=document,
        requirements=requirements,
        requirement_ids=draft_id_to_requirement,
        evidence_index=evidence_index,
    )
    preimage = {
        "need": need.to_document(),
        "requirements": [item.to_document() for item in requirements],
        "evidence_index": evidence_index.to_document(),
        "markdown": markdown,
    }
    return DevelopmentBrief(
        markdown=markdown,
        evidence_index=evidence_index,
        review_evidence_index=review_evidence_index,
        requirements=tuple(requirements),
        need=need.to_document(),
        draft=document,
        digest=_sha256(_canonical_bytes(preimage)),
    )


def _reject_downstream_prescriptions(document: Any) -> None:
    for text in _walk_strings(document):
        if any(pattern.search(text) for pattern in _FORBIDDEN_DRAFT_PATTERNS):
            raise DraftValidationError(
                "Research Draft attempts to prescribe a Builder/downstream schema or artifact"
            )


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)


def _render_brief(
    *,
    need: NeedRecord,
    draft: dict[str, Any],
    requirements: Sequence[BriefRequirement],
    requirement_ids: Mapping[str, str],
    evidence_index: EvidenceIndex,
) -> str:
    lines = [
        "# Development Brief",
        "",
        "## Original Need",
        "",
        need.original_need,
        "",
        "## Selected interpretation",
        "",
        str(draft["selected_interpretation"]),
        "",
        "## Atomic Need mapping",
        "",
    ]
    clauses = {item.clause_id: item.text for item in need.clauses}
    for mapping in cast(list[dict[str, Any]], draft["need_mapping"]):
        resolved = [requirement_ids[item] for item in cast(list[str], mapping["requirement_refs"])]
        lines.extend(
            [
                f"### {mapping['clause_id']} — {mapping['disposition']}",
                "",
                clauses[str(mapping["clause_id"])],
                "",
                f"Requirements: {', '.join(resolved) if resolved else 'none'}",
                "",
                str(mapping["rationale"]),
                "",
            ]
        )
    by_category: dict[str, list[BriefRequirement]] = {
        section: [] for section in _REQUIREMENT_SECTIONS
    }
    for requirement in requirements:
        by_category[requirement.category].append(requirement)
    display_names = {
        "capabilities": "Capabilities",
        "workflows": "Workflows",
        "invariants": "Invariants",
        "refusals": "Refusals",
        "initial_world": "Initial-world requirements",
    }
    for section in _REQUIREMENT_SECTIONS:
        lines.extend([f"## {display_names[section]}", ""])
        if not by_category[section]:
            lines.extend(["None selected.", ""])
            continue
        for item in by_category[section]:
            references = ", ".join(
                (f"`{ref['evidence_handle']}` -> `{ref['source_revision_id']}/{ref['passage_id']}`")
                for ref in item.evidence
            )
            lines.extend(
                [
                    f"### {item.requirement_id}",
                    "",
                    item.statement,
                    "",
                    f"Basis: {item.basis}",
                    "",
                    f"Observable: {item.observable}",
                    "",
                    f"Falsifiable consequence: {item.falsifiable_consequence}",
                    "",
                    (
                        f"Evidence: {references}"
                        if references
                        else "Evidence: original Need clause mapping"
                    ),
                    "",
                ]
            )
            if item.precondition is not None:
                lines.extend([f"Precondition: {item.precondition}", ""])
            if item.postcondition is not None:
                lines.extend([f"Postcondition: {item.postcondition}", ""])
            if item.refusal_condition is not None:
                lines.extend([f"Refusal condition: {item.refusal_condition}", ""])
            if item.prohibited_mutation is not None:
                lines.extend([f"Prohibited mutation: {item.prohibited_mutation}", ""])
    for key, heading in (
        ("assumptions", "Assumptions"),
        ("alternatives", "Alternatives"),
        ("exclusions", "Exclusions"),
    ):
        lines.extend([f"## {heading}", ""])
        values = cast(list[str], draft[key])
        lines.extend([*(f"- {item}" for item in values), ""] if values else ["None.", ""])
    lines.extend(["## Contradictions", ""])
    contradictions = cast(list[dict[str, Any]], draft["contradictions"])
    if contradictions:
        for contradiction in contradictions:
            lines.extend([f"- {contradiction['topic']}: {contradiction['resolution']}"])
    else:
        lines.append("None disclosed.")
    lines.extend(["", "## Open gaps", ""])
    gaps = cast(list[dict[str, Any]], draft["open_gaps"])
    lines.extend([*(f"- {gap['clause_id']}: {gap['description']}" for gap in gaps)] or ["None."])
    lines.extend(["", evidence_index.to_markdown(), ""])
    return "\n".join(lines)


@dataclass(frozen=True)
class EvidenceReview:
    clause_findings: tuple[dict[str, Any], ...]
    requirement_findings: tuple[dict[str, Any], ...]
    scope_assessment: dict[str, Any]
    residual_limitations: tuple[str, ...]
    unsupported_findings: tuple[dict[str, Any], ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "clause_findings": [_json_copy(item) for item in self.clause_findings],
            "requirement_findings": [_json_copy(item) for item in self.requirement_findings],
            "scope_assessment": _json_copy(self.scope_assessment),
            "residual_limitations": list(self.residual_limitations),
            "unsupported_findings": [_json_copy(item) for item in self.unsupported_findings],
        }


@dataclass(frozen=True)
class ResearchReady:
    brief: DevelopmentBrief
    review: EvidenceReview
    builder_projection: BuilderProjection
    digest: str

    def to_document(self) -> dict[str, Any]:
        return {
            "brief": self.brief.to_document(),
            "review": self.review.to_document(),
            "builder_projection": self.builder_projection.to_document(),
            "digest": self.digest,
        }

    def write(self, path: Path) -> None:
        """Persist the accepted Research handoff as one canonical, immutable JSON carrier."""
        destination = Path(path)
        if destination.is_symlink() or destination.exists():
            raise FileExistsError(f"ResearchReady carrier already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_canonical_bytes(self.to_document()))
        destination.chmod(0o444)


@dataclass(frozen=True)
class NotReleased:
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class Unsupported:
    code: str
    message: str
    details: dict[str, Any]


ReviewAction = Literal["ACCEPT", "REVISE", "UNSUPPORTED"]


def validate_evidence_review(*, brief: DevelopmentBrief, review: EvidenceReview) -> None:
    """Validate coverage, authority and evidence closure at the acceptance boundary."""

    def fail(code: str, message: str, **details: Any) -> None:
        raise ResearchFailure(
            phase="reviewer",
            code=code,
            message=message,
            details={"original_code": code, "original_message": message, **details},
        )

    expected_clauses = [
        str(item["clause_id"]) for item in cast(list[dict[str, Any]], brief.need.get("clauses", []))
    ]
    actual_clauses = [str(item.get("clause_id")) for item in review.clause_findings]
    if actual_clauses != expected_clauses:
        fail(
            "reviewer_clause_coverage_invalid",
            "reviewer must return exactly one ordered finding per Need clause",
            expected=expected_clauses,
            actual=actual_clauses,
        )

    requirements = {item.requirement_id: item for item in brief.requirements}
    expected_requirements = list(requirements)
    actual_requirements = [str(item.get("requirement_id")) for item in review.requirement_findings]
    if actual_requirements != expected_requirements:
        fail(
            "reviewer_requirement_coverage_invalid",
            "reviewer must return exactly one ordered finding per Brief requirement",
            expected=expected_requirements,
            actual=actual_requirements,
        )

    visible_handles = {item.evidence_handle for item in brief.review_evidence_index.entries}

    def validate_refs(references: Any, *, target: str) -> set[str]:
        if not isinstance(references, list):
            fail("reviewer_evidence_shape_invalid", "evidence_refs must be an array", target=target)
        handles = [
            str(item.get("evidence_handle")) for item in references if isinstance(item, dict)
        ]
        if len(handles) != len(references) or len(handles) != len(set(handles)):
            fail(
                "reviewer_evidence_shape_invalid",
                "evidence_refs must contain unique evidence-handle objects",
                target=target,
            )
        unknown = sorted(set(handles) - visible_handles)
        if unknown:
            fail(
                "reviewer_evidence_outside_bounded_index",
                "reviewer cited evidence outside the bounded review index",
                target=target,
                unknown=unknown,
            )
        return set(handles)

    clause_judgments = {
        "supported",
        "omitted",
        "contradicted",
        "unjustified_narrowing",
    }
    for finding in review.clause_findings:
        clause_id = str(finding["clause_id"])
        if finding.get("judgment") not in clause_judgments:
            fail(
                "reviewer_clause_judgment_invalid",
                "Need clauses cannot be reclassified as selectable authority",
                clause_id=clause_id,
                judgment=finding.get("judgment"),
            )
        if not str(finding.get("rationale") or "").strip():
            fail("reviewer_rationale_empty", "clause finding requires rationale", target=clause_id)
        validate_refs(finding.get("evidence_refs"), target=clause_id)

    for finding in review.requirement_findings:
        requirement_id = str(finding["requirement_id"])
        requirement = requirements[requirement_id]
        judgment = finding.get("judgment")
        allowed = (
            {"supported", "contradicted", "authority_mismatch"}
            if requirement.basis == "need"
            else {"supported", "not_entailed", "contradicted", "authority_mismatch"}
        )
        if judgment not in allowed:
            fail(
                "reviewer_requirement_judgment_invalid",
                "requirement judgment is incompatible with its Host-known basis",
                requirement_id=requirement_id,
                basis=requirement.basis,
                judgment=judgment,
            )
        if not str(finding.get("rationale") or "").strip():
            fail(
                "reviewer_rationale_empty",
                "requirement finding requires rationale",
                target=requirement_id,
            )
        handles = validate_refs(finding.get("evidence_refs"), target=requirement_id)
        requirement_handles = {str(item["evidence_handle"]) for item in requirement.evidence}
        if requirement.basis == "need" and handles:
            fail(
                "reviewer_need_evidence_forbidden",
                "Need-basis requirements must not be made web-contingent",
                requirement_id=requirement_id,
            )
        if requirement.basis == "external_evidence" and (
            not handles or not handles.issubset(requirement_handles)
        ):
            fail(
                "reviewer_external_evidence_mismatch",
                "external requirement findings must cite its own evaluated evidence",
                requirement_id=requirement_id,
                expected=sorted(requirement_handles),
                actual=sorted(handles),
            )

    scope_judgment = review.scope_assessment.get("judgment")
    if scope_judgment not in {
        "supported",
        "acceptable_selection",
        "unjustified_narrowing",
    }:
        fail("reviewer_scope_invalid", "scope assessment judgment is invalid")
    if not str(review.scope_assessment.get("rationale") or "").strip():
        fail("reviewer_scope_rationale_empty", "scope assessment requires rationale")
    for index, limitation in enumerate(review.residual_limitations):
        if not limitation.strip():
            fail(
                "reviewer_residual_limitation_empty",
                "residual limitations must be non-empty",
                index=index,
            )

    unsupported_ids = [str(item.get("clause_id")) for item in review.unsupported_findings]
    unknown_ids = sorted(set(unsupported_ids) - set(expected_clauses))
    if unknown_ids:
        fail(
            "reviewer_unsupported_clause_unknown",
            "unsupported proposal names unknown Need clauses",
            unknown=unknown_ids,
        )
    if len(unsupported_ids) != len(set(unsupported_ids)):
        fail(
            "reviewer_unsupported_duplicate",
            "unsupported findings must name each Need clause at most once",
        )
    for finding in review.unsupported_findings:
        clause_id = str(finding["clause_id"])
        if not str(finding.get("rationale") or "").strip():
            fail(
                "reviewer_unsupported_finding_incomplete",
                "unsupported finding requires a rationale",
                clause_id=clause_id,
            )
        validate_refs(
            finding.get("evidence_refs", []),
            target=f"unsupported:{clause_id}",
        )


def aggregate_evidence_review(*, brief: DevelopmentBrief, review: EvidenceReview) -> ReviewAction:
    """Derive the Research action from typed findings; the LLM owns no terminal verdict."""
    validate_evidence_review(brief=brief, review=review)
    blocking_clause = {"omitted", "contradicted", "unjustified_narrowing"}
    blocking_requirement = {"not_entailed", "contradicted", "authority_mismatch"}
    if any(item.get("judgment") in blocking_clause for item in review.clause_findings):
        return "REVISE"
    if any(item.get("judgment") in blocking_requirement for item in review.requirement_findings):
        return "REVISE"
    if review.scope_assessment.get("judgment") == "unjustified_narrowing":
        return "REVISE"

    producer_unsupported = {
        str(item["clause_id"])
        for item in cast(list[dict[str, Any]], brief.draft.get("need_mapping", []))
        if item.get("disposition") == "unsupported"
    }
    reviewer_unsupported = {str(item["clause_id"]) for item in review.unsupported_findings}
    if reviewer_unsupported:
        if reviewer_unsupported == producer_unsupported:
            return "UNSUPPORTED"
        return "REVISE"
    if producer_unsupported:
        return "REVISE"

    core_gaps = [
        item
        for item in cast(list[dict[str, Any]], brief.draft.get("open_gaps", []))
        if item["can_change_core_requirement"] is True
    ]
    if core_gaps:
        return "REVISE"
    return "ACCEPT"


def _derive_builder_projection(
    *, brief: DevelopmentBrief, review: EvidenceReview
) -> BuilderProjection:
    origins: dict[str, list[str]] = {}
    for mapping in cast(list[dict[str, Any]], brief.draft["need_mapping"]):
        for draft_id in cast(list[str], mapping["requirement_refs"]):
            origins.setdefault(draft_id, []).append(str(mapping["clause_id"]))

    requirements: list[dict[str, Any]] = []
    initial_world_relations: list[dict[str, Any]] = []
    for requirement in brief.requirements:
        evidence_refs = [
            {"evidence_handle": str(reference["evidence_handle"])}
            for reference in requirement.evidence
        ]
        if requirement.category == "initial_world":
            initial_world_relations.append(
                {
                    "id": requirement.requirement_id,
                    "need_origins": origins[requirement.draft_id],
                    "authority": requirement.basis,
                    "state_relation": requirement.statement,
                    "observable_relation": requirement.observable,
                    "falsifiable_consequence": requirement.falsifiable_consequence,
                    "evidence_refs": evidence_refs,
                }
            )
            continue
        projected_requirement = {
            "id": requirement.requirement_id,
            "need_origins": origins[requirement.draft_id],
            "authority": requirement.basis,
            "kind": requirement.category,
            "state_relation": requirement.statement,
            "observable_relation": requirement.observable,
            "falsifiable_consequence": requirement.falsifiable_consequence,
            "evidence_refs": evidence_refs,
        }
        for field_name in (
            "precondition",
            "postcondition",
            "refusal_condition",
            "prohibited_mutation",
        ):
            value = getattr(requirement, field_name)
            if value is not None:
                projected_requirement[field_name] = value
        requirements.append(projected_requirement)

    residual_limitations = list(review.residual_limitations)
    for gap in cast(list[dict[str, Any]], brief.draft["open_gaps"]):
        description = str(gap["description"])
        if description not in residual_limitations:
            residual_limitations.append(description)

    return BuilderProjection(
        frozen_need=brief.need,
        selected_world={
            "scope": brief.draft["selected_interpretation"],
            "assumptions": brief.draft.get("assumptions", []),
            "exclusions": brief.draft.get("exclusions", []),
            "residual_limitations": residual_limitations,
        },
        requirements=tuple(requirements),
        initial_world_relations=tuple(initial_world_relations),
        cited_evidence=tuple(entry.to_document() for entry in brief.evidence_index.entries),
    )


def finalize_research(
    *,
    brief: DevelopmentBrief,
    review: EvidenceReview,
) -> ResearchReady | NotReleased | Unsupported:
    """Map Host-owned aggregation without accepting an LLM-authored terminal verdict."""
    action = aggregate_evidence_review(brief=brief, review=review)
    if action == "ACCEPT":
        builder_projection = _derive_builder_projection(brief=brief, review=review)
        preimage = {
            "brief": brief.to_document(),
            "review": review.to_document(),
            "builder_projection": builder_projection.to_document(),
        }
        return ResearchReady(
            brief=brief,
            review=review,
            builder_projection=builder_projection,
            digest=_sha256(_canonical_bytes(preimage)),
        )
    if action == "UNSUPPORTED":
        return Unsupported(
            code="unsupported_need",
            message=(
                "Research and independent review agree that explicit Need clauses are unsupported"
            ),
            details={
                "unsupported_findings": [_json_copy(item) for item in review.unsupported_findings]
            },
        )
    return NotReleased(
        code="review_requires_revision",
        message="typed Evidence Reviewer findings require Research revision",
        details={
            "clause_findings": [_json_copy(item) for item in review.clause_findings],
            "requirement_findings": [_json_copy(item) for item in review.requirement_findings],
            "scope_assessment": _json_copy(review.scope_assessment),
            "residual_limitations": list(review.residual_limitations),
            "unsupported_findings": [_json_copy(item) for item in review.unsupported_findings],
            "declared_open_gaps": _json_copy(brief.draft.get("open_gaps", [])),
        },
    )

"""Safety limits for untrusted research content before Artifact or Agent use."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import ExtractedDocument

MAX_RAW_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_RESEARCH_RAW_BYTES = 32 * 1024 * 1024
MAX_RESEARCH_EXTRACTED_BYTES = 16 * 1024 * 1024

_HIGH_CONFIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I),
    ),
    ("aws-access-key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("openai-key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("jina-key", re.compile(rb"\bjina_[A-Za-z0-9_-]{20,}\b", re.I)),
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"[\"']?(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)[\"']?"
    rb"\s*[=:]\s*[\"']?([A-Za-z0-9_./+~=-]{16,})",
    re.I,
)
_BEARER = re.compile(rb"\bbearer\s+([A-Za-z0-9._~+/=-]{16,})", re.I)
_URL_CREDENTIAL_NAME = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?token|auth|authorization|client[_-]?secret|"
    r"credential|password|private[_-]?key|refresh[_-]?token|secret|session|sig|signature|"
    r"token)(?:$|[_-])",
    re.I,
)
_PLACEHOLDER_PARTS = (
    b"example",
    b"placeholder",
    b"replace",
    b"sample",
    b"test",
    b"your",
    b"xxxxx",
)


class ResearchSafetyError(RuntimeError):
    """Untrusted source content cannot cross into Artifacts or Agent workspaces."""


def normalize_research_text(value: str) -> str:
    """Normalize Unicode/newlines and remove invisible controls without truncating text."""

    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    cleaned: list[str] = []
    for character in normalized:
        if character in {"\n", "\t"}:
            cleaned.append(character)
        elif unicodedata.category(character).startswith("C"):
            cleaned.append(" ")
        else:
            cleaned.append(character)
    return "".join(cleaned).strip()


def sensitive_url_parameter(name: str) -> bool:
    """Return whether a URL parameter name could carry a credential."""

    return _URL_CREDENTIAL_NAME.search(name.strip()) is not None


def assert_secret_free(
    content: bytes,
    *,
    known_secret_values: Iterable[str] = (),
    context: str,
) -> None:
    """Reject high-confidence credentials without including their value in errors."""

    for value in known_secret_values:
        encoded = value.encode("utf-8")
        if len(encoded) >= 4 and encoded in content:
            raise ResearchSafetyError(f"{context} contains an authorized credential value")
    for label, pattern in _HIGH_CONFIDENCE_PATTERNS:
        if pattern.search(content):
            raise ResearchSafetyError(f"{context} contains credential-like material ({label})")
    for pattern, label in (
        (_CREDENTIAL_ASSIGNMENT, "credential-assignment"),
        (_BEARER, "bearer-token"),
    ):
        for match in pattern.finditer(content):
            candidate = match.group(1).lower()
            if not any(part in candidate for part in _PLACEHOLDER_PARTS):
                raise ResearchSafetyError(
                    f"{context} contains credential-like material ({label})"
                )


def assert_safe_research_document(
    document: ExtractedDocument,
    *,
    known_secret_values: Iterable[str] = (),
) -> tuple[int, int]:
    """Validate one complete raw/extracted source and return its byte sizes."""

    raw_size = len(document.source.body)
    extracted = document.text.encode("utf-8")
    extracted_size = len(extracted)
    if raw_size > MAX_RAW_DOCUMENT_BYTES:
        raise ResearchSafetyError("raw research document exceeds the fixed 8 MiB limit")
    if extracted_size > MAX_EXTRACTED_DOCUMENT_BYTES:
        raise ResearchSafetyError("extracted research document exceeds the fixed 2 MiB limit")
    assert_secret_free(
        document.source.body,
        known_secret_values=known_secret_values,
        context="raw research document",
    )
    assert_secret_free(
        extracted,
        known_secret_values=known_secret_values,
        context="extracted research document",
    )
    provenance = "\n".join(
        (
            document.source.requested_url,
            document.source.final_url,
            *(f"{name}: {value}" for name, value in document.source.response_headers),
        )
    ).encode("utf-8")
    assert_secret_free(
        provenance,
        known_secret_values=known_secret_values,
        context="research provenance",
    )
    if document.title is not None:
        assert_secret_free(
            document.title.encode("utf-8"),
            known_secret_values=known_secret_values,
            context="research document title",
        )
    return raw_size, extracted_size


__all__ = [
    "MAX_EXTRACTED_DOCUMENT_BYTES",
    "MAX_RAW_DOCUMENT_BYTES",
    "MAX_RESEARCH_EXTRACTED_BYTES",
    "MAX_RESEARCH_RAW_BYTES",
    "ResearchSafetyError",
    "assert_safe_research_document",
    "assert_secret_free",
    "normalize_research_text",
    "sensitive_url_parameter",
]

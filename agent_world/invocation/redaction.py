"""Fail-closed recursive redaction used on both sides of the worker boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import JsonValue

REDACTED = "[REDACTED]"

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_TERMINAL_DIAGNOSTIC_URL = re.compile(r"(?i)\b(?:https?|wss?|file)://[^\s'\"<>]+")
_TERMINAL_DIAGNOSTIC_ASSIGNMENT = re.compile(
    r"(?i)\b(api[ _-]?key|authorization|token|secret|password)\b\s*[:=]\s*\S+"
)
_TERMINAL_DIAGNOSTIC_OPAQUE = re.compile(r"\b[A-Za-z0-9._~+/=-]{32,}\b")
_LOCAL_DIAGNOSTIC_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9._-])/(?:[^\s'\"<>]+)")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")
_SENSITIVE_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "access_token",
        "refresh_token",
        "auth_token",
        "id_token",
    }
)


@dataclass(frozen=True, slots=True)
class Redactor:
    """Redact known values, common credential shapes, and sensitive keys."""

    secret_values: tuple[str, ...] = ()

    @classmethod
    def from_values(cls, values: Iterable[str]) -> Redactor:
        unique = sorted({value for value in values if len(value) >= 4}, key=len, reverse=True)
        return cls(tuple(unique))

    def text(self, value: str) -> str:
        output = value
        for secret in self.secret_values:
            output = output.replace(secret, REDACTED)
        output = _BEARER.sub(REDACTED, output)
        output = _OPENAI_KEY.sub(REDACTED, output)
        return output

    def value(self, value: Any, *, key: str | None = None) -> JsonValue:
        if key is not None and _sensitive_key(key):
            return REDACTED
        if value is None or isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {
                str(item_key): self.value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return self.text(str(value))

    def object(self, value: Mapping[str, Any]) -> dict[str, JsonValue]:
        normalized = self.value(value)
        if not isinstance(normalized, dict):
            raise TypeError("redacted object did not remain an object")
        return normalized


def redacted_terminal_diagnostic_excerpt(
    value: object,
    *,
    redactor: Redactor,
    maximum_characters: int = 512,
) -> str | None:
    """Return one bounded local-only terminal excerpt after defensive redaction.

    This is deliberately narrower than :meth:`Redactor.text`.  It is used
    only by an explicitly opted-in diagnostic side channel, never ordinary
    runtime feedback.  Provider terminal text can contain routes, credential
    assignments, or opaque request material, so callers must receive a
    compact, second-pass-scrubbed string even when a worker has already
    redacted it.
    """

    if not isinstance(value, str) or maximum_characters <= 0:
        return None
    text = redactor.text(value)
    text = _TERMINAL_DIAGNOSTIC_URL.sub("[REDACTED_URL]", text)
    text = _TERMINAL_DIAGNOSTIC_ASSIGNMENT.sub(r"\1=[REDACTED]", text)
    text = _TERMINAL_DIAGNOSTIC_OPAQUE.sub("[REDACTED_OPAQUE]", text)
    compact = " ".join(text.split())
    return compact[:maximum_characters] if compact else None


def redacted_local_diagnostic_excerpt(
    value: object,
    *,
    redactor: Redactor,
    maximum_characters: int = 256,
) -> str | None:
    """Return a local-only diagnostic excerpt without filesystem detail.

    App-server startup failures can include host paths as well as routes and
    credentials.  A project-execution Agent only needs the failure shape, so
    retain a bounded redacted excerpt while removing those local paths.  This
    helper is deliberately general: it does not assert an old tool façade or
    any filesystem-isolation topology.
    """

    excerpt = redacted_terminal_diagnostic_excerpt(
        value,
        redactor=redactor,
        maximum_characters=maximum_characters,
    )
    if excerpt is None:
        return None
    return _LOCAL_DIAGNOSTIC_ABSOLUTE_PATH.sub("[REDACTED_PATH]", excerpt)


def _sensitive_key(value: str) -> bool:
    normalized = _CAMEL_BOUNDARY.sub("_", value).replace("-", "_").lower()
    if normalized in _SENSITIVE_NAMES:
        return True
    return any(normalized.endswith(f"_{name}") for name in _SENSITIVE_NAMES)

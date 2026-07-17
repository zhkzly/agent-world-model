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


def _sensitive_key(value: str) -> bool:
    normalized = _CAMEL_BOUNDARY.sub("_", value).replace("-", "_").lower()
    if normalized in _SENSITIVE_NAMES:
        return True
    return any(normalized.endswith(f"_{name}") for name in _SENSITIVE_NAMES)

"""Closed stdin/stdout worker for native Trafilatura extraction.

This module is intentionally executable only as a subprocess.  It owns the
native lxml/libxml2 import so a fatal parser signal cannot terminate the
long-lived Foundry Controller.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import resource
import sys
from typing import NoReturn

import trafilatura

from .security import MAX_EXTRACTED_DOCUMENT_BYTES, MAX_RAW_DOCUMENT_BYTES

_PROTOCOL = "agent-world.trafilatura-extract.v1"
_MAX_REQUEST_BYTES = ((MAX_RAW_DOCUMENT_BYTES + 2) // 3 * 4) + 32 * 1024
_MAX_URL_CHARACTERS = 8 * 1024
_MAX_TIMEOUT_SECONDS = 300.0


class ExtractWorkerProtocolError(RuntimeError):
    """The parent sent a request outside the closed extraction protocol."""


def _read_request() -> dict[str, object]:
    payload = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ExtractWorkerProtocolError("request exceeded its fixed byte limit")
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ExtractWorkerProtocolError("request is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "body_base64",
        "url",
        "timeout_seconds",
    }:
        raise ExtractWorkerProtocolError("request does not match the closed schema")
    if value.get("protocol") != _PROTOCOL:
        raise ExtractWorkerProtocolError("request protocol version is unsupported")
    return value


def _decode_request(value: dict[str, object]) -> tuple[str, str, float]:
    encoded = value["body_base64"]
    url = value["url"]
    timeout = value["timeout_seconds"]
    if not isinstance(encoded, str):
        raise ExtractWorkerProtocolError("body_base64 must be a string")
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_CHARACTERS:
        raise ExtractWorkerProtocolError("url is invalid")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ExtractWorkerProtocolError("timeout_seconds must be numeric")
    timeout_seconds = float(timeout)
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise ExtractWorkerProtocolError("timeout_seconds is outside its fixed range")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ExtractWorkerProtocolError("body_base64 is invalid") from exc
    if len(body) > MAX_RAW_DOCUMENT_BYTES:
        raise ExtractWorkerProtocolError("decoded body exceeded its fixed byte limit")
    return body.decode("utf-8", errors="replace"), url, timeout_seconds


def _apply_limits(timeout_seconds: float) -> None:
    cpu_seconds = max(1, min(300, math.ceil(timeout_seconds)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    # Trafilatura/lxml normally uses far less; this leaves room for the 8 MiB
    # source and parser structures while bounding pathological expansion.
    memory_bytes = 1024 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _emit(value: dict[str, object]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _safe_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return (message or "extractor rejected the document")[:500]


def main() -> int:
    try:
        request = _read_request()
        document, url, timeout_seconds = _decode_request(request)
        _apply_limits(timeout_seconds)
        text = (
            trafilatura.extract(
                document,
                url=url,
                include_links=True,
                include_tables=True,
                favor_recall=True,
            )
            or ""
        )
        if len(text.encode("utf-8")) > MAX_EXTRACTED_DOCUMENT_BYTES:
            raise ExtractWorkerProtocolError("extracted text exceeded its fixed byte limit")
        _emit({"protocol": _PROTOCOL, "status": "ok", "text": text})
        return 0
    except Exception as exc:
        _emit(
            {
                "protocol": _PROTOCOL,
                "status": "error",
                "error_type": type(exc).__name__,
                "message": _safe_error_message(exc),
            }
        )
        return 0


def _entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _entrypoint()

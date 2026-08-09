"""Immutable local artifact storage and secret-safe persistence helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_world.contracts import ArtifactRef, json_value

_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "prompt",
        "raw_prompt",
        "transcript",
        "sealed_case",
        "evaluator_goal",
    }
)
_FORBIDDEN_KEY_PARTS = (
    "credential",
    "secret",
    "prompt",
    "transcript",
    "provider_payload",
    "raw_response",
    "sealed",
    "evaluator",
    "expected_output",
    "expected_state",
)
_CANDIDATE_CONTROL_CLAIM_KEYS = frozenset(
    {"gate", "gates", "judge", "judge_report", "release", "receipt", "verdict", "published"}
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?:api[_-]?key|authorization|password)\s*[:=]", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
)
_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})\Z")
_KIND_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}\Z")
_RUN_STATUSES = frozenset(
    {"running", "released", "rejected", "needs_human", "budget_exhausted", "error"}
)


class ArtifactSafetyError(ValueError):
    pass


class ArtifactIntegrityError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactSafetyError("artifact_not_json_safe") from exc


def _assert_safe(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_KEYS or any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                raise ArtifactSafetyError("artifact_forbidden_field")
            _assert_safe(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_safe(item, path)
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ArtifactSafetyError("artifact_secret_like_value")


def _assert_no_candidate_control_claim(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _CANDIDATE_CONTROL_CLAIM_KEYS:
                raise ArtifactSafetyError("candidate_control_claim")
            _assert_no_candidate_control_claim(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_candidate_control_claim(item)


def safe_url(url: str) -> str:
    """Keep provenance origin/path while never persisting query or fragment."""

    return url.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]


def _digest_hex(value: object, *, error: type[ValueError]) -> str:
    if not isinstance(value, str):
        raise error("artifact_digest_invalid")
    match = _DIGEST_PATTERN.fullmatch(value)
    if match is None:
        raise error("artifact_digest_invalid")
    return match.group(1)


def _media_suffix(media_type: object, *, error: type[ValueError]) -> str:
    if media_type == "application/json":
        return ".json"
    if media_type == "application/zip":
        return ".zip"
    raise error("artifact_media_type_invalid")


def _validate_ref(
    artifact_id: object,
    kind: object,
    digest: object,
    path: object,
    media_type: object,
    *,
    error: type[ValueError],
) -> None:
    if not isinstance(kind, str) or _KIND_PATTERN.fullmatch(kind) is None:
        raise error("artifact_kind_invalid")
    digest_hex = _digest_hex(digest, error=error)
    suffix = _media_suffix(media_type, error=error)
    expected_id = f"{kind}:{digest_hex[:16]}"
    expected_path = f"artifacts/{digest_hex}{suffix}"
    if artifact_id != expected_id or path != expected_path:
        raise error("artifact_ref_invalid")


def _validate_ref_mapping(value: object, *, error: type[ValueError]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "artifact_id",
        "kind",
        "digest",
        "path",
        "media_type",
    }:
        raise error("artifact_ref_invalid")
    _validate_ref(
        value["artifact_id"],
        value["kind"],
        value["digest"],
        value["path"],
        value["media_type"],
        error=error,
    )


def _safe_token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN_PATTERN.fullmatch(value) is not None


def _validate_run_fact(value: object, *, error: type[ValueError]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "run_id",
        "request_id",
        "request_digest",
        "status",
        "started_at",
        "ended_at",
        "events",
        "artifacts",
        "release",
    }:
        raise error("run_invalid")
    if not _safe_token(value["run_id"]) or not _safe_token(value["request_id"]):
        raise error("run_invalid")
    _digest_hex(value["request_digest"], error=error)
    if not isinstance(value["status"], str) or value["status"] not in _RUN_STATUSES:
        raise error("run_invalid")
    if not isinstance(value["started_at"], str) or not isinstance(
        value["ended_at"], (str, type(None))
    ):
        raise error("run_invalid")

    events = value["events"]
    if not isinstance(events, list):
        raise error("run_invalid")
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "stage",
            "status",
            "at",
            "code",
            "artifact_ids",
        }:
            raise error("run_invalid")
        if not _safe_token(event["stage"]) or not _safe_token(event["status"]):
            raise error("run_invalid")
        if event["code"] is not None and not _safe_token(event["code"]):
            raise error("run_invalid")
        if not isinstance(event["at"], str) or not isinstance(event["artifact_ids"], list):
            raise error("run_invalid")
        if not all(_safe_token(item) for item in event["artifact_ids"]):
            raise error("run_invalid")

    artifacts = value["artifacts"]
    if not isinstance(artifacts, list):
        raise error("run_invalid")
    for artifact in artifacts:
        _validate_ref_mapping(artifact, error=error)

    release = value["release"]
    if release is None:
        if value["status"] == "released":
            raise error("released_receipt_required")
        return
    if (
        value["status"] != "released"
        or not isinstance(release, dict)
        or set(release)
        != {
            "package_id",
            "version",
            "package_digest",
            "receipt_digest",
            "artifact",
        }
    ):
        raise error("run_invalid")
    if not _safe_token(release["package_id"]) or not _safe_token(release["version"]):
        raise error("run_invalid")
    _digest_hex(release["package_digest"], error=error)
    _digest_hex(release["receipt_digest"], error=error)
    _validate_ref_mapping(release["artifact"], error=error)


class ArtifactStore:
    """Content-addressed records under one Direct run root."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.artifacts_root = run_root / "artifacts"

    def put_json(self, kind: str, value: Any) -> ArtifactRef:
        if _KIND_PATTERN.fullmatch(kind) is None:
            raise ArtifactSafetyError("artifact_kind_invalid")
        safe_value = json_value(value)
        _assert_safe(safe_value)
        if kind.startswith("candidate."):
            _assert_no_candidate_control_claim(safe_value)
        payload = canonical_json({"kind": kind, "payload": safe_value})
        digest = f"sha256:{sha256(payload).hexdigest()}"
        filename = f"{digest.removeprefix('sha256:')}.json"
        path = self.artifacts_root / filename
        self._write_immutable(path, payload)
        return ArtifactRef(
            artifact_id=f"{kind}:{digest.removeprefix('sha256:')[:16]}",
            kind=kind,
            digest=digest,
            path=str(Path("artifacts") / filename),
        )

    def put_bytes(self, kind: str, body: bytes, *, media_type: str) -> ArtifactRef:
        if _KIND_PATTERN.fullmatch(kind) is None:
            raise ArtifactSafetyError("artifact_kind_invalid")
        if not isinstance(body, bytes) or media_type != "application/zip":
            raise ArtifactSafetyError("artifact_bytes_not_allowed")
        digest = f"sha256:{sha256(body).hexdigest()}"
        filename = f"{digest.removeprefix('sha256:')}.zip"
        path = self.artifacts_root / filename
        self._write_immutable(path, body)
        return ArtifactRef(
            artifact_id=f"{kind}:{digest.removeprefix('sha256:')[:16]}",
            kind=kind,
            digest=digest,
            path=str(Path("artifacts") / filename),
            media_type=media_type,
        )

    def read_bytes(self, ref: ArtifactRef) -> bytes:
        _validate_ref(
            ref.artifact_id,
            ref.kind,
            ref.digest,
            ref.path,
            ref.media_type,
            error=ArtifactIntegrityError,
        )
        path = self.run_root / ref.path
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError("artifact_missing") from exc
        if f"sha256:{sha256(body).hexdigest()}" != ref.digest:
            raise ArtifactIntegrityError("artifact_digest_mismatch")
        return body

    def read_json(self, ref: ArtifactRef) -> Any:
        if ref.media_type != "application/json":
            raise ArtifactIntegrityError("artifact_not_json")
        body = self.read_bytes(ref)
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ArtifactIntegrityError("artifact_invalid_json") from exc
        if not isinstance(envelope, dict) or envelope.get("kind") != ref.kind:
            raise ArtifactIntegrityError("artifact_kind_mismatch")
        try:
            canonical_envelope = canonical_json(envelope)
        except ArtifactSafetyError as exc:
            raise ArtifactIntegrityError("artifact_noncanonical") from exc
        if set(envelope) != {"kind", "payload"} or canonical_envelope != body:
            raise ArtifactIntegrityError("artifact_noncanonical")
        try:
            _assert_safe(envelope["payload"])
        except ArtifactSafetyError as exc:
            raise ArtifactIntegrityError("artifact_unsafe") from exc
        return envelope["payload"]

    def write_run(self, value: Any) -> None:
        safe_value = json_value(value)
        _assert_safe(safe_value)
        _validate_run_fact(safe_value, error=ArtifactSafetyError)
        fact = canonical_json(safe_value)
        self._write_atomic(
            self.run_root / "run.json",
            canonical_json({"digest": f"sha256:{sha256(fact).hexdigest()}", "payload": safe_value}),
        )

    def read_run(self) -> dict[str, Any]:
        try:
            body = (self.run_root / "run.json").read_bytes()
            value = json.loads(body)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("run_unreadable") from exc
        if not isinstance(value, dict) or set(value) != {"digest", "payload"}:
            raise ArtifactIntegrityError("run_invalid")
        payload = value.get("payload")
        try:
            canonical_value = canonical_json(value)
        except ArtifactSafetyError as exc:
            raise ArtifactIntegrityError("run_invalid") from exc
        if not isinstance(payload, dict) or canonical_value != body:
            raise ArtifactIntegrityError("run_invalid")
        try:
            _assert_safe(payload)
            _validate_run_fact(payload, error=ArtifactIntegrityError)
        except ArtifactSafetyError as exc:
            raise ArtifactIntegrityError("run_unsafe") from exc
        try:
            fact = canonical_json(payload)
        except ArtifactSafetyError as exc:
            raise ArtifactIntegrityError("run_invalid") from exc
        if value.get("digest") != f"sha256:{sha256(fact).hexdigest()}":
            raise ArtifactIntegrityError("run_digest_mismatch")
        return payload

    @staticmethod
    def _write_atomic(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_immutable(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                try:
                    existing = path.read_bytes()
                except OSError as exc:
                    raise ArtifactIntegrityError("artifact_unreadable") from exc
                if existing != body:
                    raise ArtifactIntegrityError("artifact_hash_collision") from None
        finally:
            temporary.unlink(missing_ok=True)

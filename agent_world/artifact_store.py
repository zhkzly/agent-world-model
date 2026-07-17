"""Content-addressed, immutable storage for Agent World control-plane artifacts.

The store intentionally has no update or delete operation.  A repair commits a
new revision whose manifest names the exact dependency revisions it consumed.
Candidate source code, evidence documents, and large evaluation output are
stored as blobs; cross-component JSON is stored in canonical form.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, overload

from pydantic import AwareDatetime, BaseModel

from agent_world.contracts import (
    ArtifactRef,
    Identifier,
    KeyValue,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
_ATTESTATION_PATTERN = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_SCOPE_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PROVENANCE_KEY_NAME = ".producer-provenance.key"
_PROVENANCE_KEY_BYTES = 32
_FORBIDDEN_ARTIFACT_TYPE_PARTS = frozenset({"secret", "transcript", "rawprompt", "rawresponse"})
_FORBIDDEN_VALUE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "credential_value",
        "password_value",
        "private_key",
        "raw_prompt",
        "raw_response",
        "refresh_token",
        "secret",
        "secret_value",
        "transcript",
    }
)
_SCHEMA_NAME_CONTAINERS = frozenset({"$defs", "definitions", "patternProperties", "properties"})
_SENSITIVE_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-key",
        re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    ),
    ("aws-access-key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("openai-key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("jina-key", re.compile(rb"\bjina_[A-Za-z0-9_-]{20,}\b", re.IGNORECASE)),
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
    rb"\s*[=:]\s*[\"']?([A-Za-z0-9_./+~=-]{16,})",
    re.IGNORECASE,
)
_BEARER_CREDENTIAL = re.compile(rb"\bbearer\s+([A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)
_CREDENTIAL_PLACEHOLDERS = (
    b"example",
    b"placeholder",
    b"replace",
    b"sample",
    b"test",
    b"your",
    b"xxxxx",
)


class ArtifactStoreError(RuntimeError):
    """Base error for local store failures."""


class ArtifactNotFoundError(ArtifactStoreError):
    pass


class ArtifactIntegrityError(ArtifactStoreError):
    pass


class UnsafeArtifactError(ArtifactStoreError):
    pass


class ProducerCapability(V2Contract):
    """Store-issued immutable authority carried by every durable write.

    The capability contains no signing key.  Its attestation proves that the
    store issued this exact producer/scope tuple; an :class:`ArtifactWriter`
    is the only public object that can exercise it.
    """

    capability_id: Identifier
    producer: Identifier
    allowed_artifact_types: tuple[Identifier, ...] = ()
    allowed_artifact_type_prefixes: tuple[str, ...] = ()
    allowed_artifact_id_prefixes: tuple[str, ...] = ()
    allowed_event_types: tuple[Identifier, ...] = ()
    allowed_event_type_prefixes: tuple[str, ...] = ()
    attestation: str


class ArtifactRevision(V2Contract):
    """Deterministic revision manifest with signed producer provenance."""

    ref: ArtifactRef
    dependency_refs: tuple[ArtifactRef, ...] = ()
    capability: ProducerCapability
    producer_attestation: str

    @property
    def producer(self) -> str:
        return self.capability.producer


class ArtifactEvent(V2Contract):
    event_id: Identifier
    event_type: Identifier
    occurred_at: AwareDatetime
    subject_ref: ArtifactRef
    related_refs: tuple[ArtifactRef, ...] = ()
    capability: ProducerCapability
    reason_code: Identifier | None = None
    details: tuple[KeyValue, ...] = ()
    producer_attestation: str

    @property
    def producer(self) -> str:
        return self.capability.producer


TModel = TypeVar("TModel", bound=BaseModel)


def _is_probable_credential(candidate: bytes) -> bool:
    return (
        not any(part in candidate for part in _CREDENTIAL_PLACEHOLDERS)
        and any(48 <= value <= 57 for value in candidate)
        and any(65 <= value <= 90 or 97 <= value <= 122 for value in candidate)
    )


class ArtifactWriter:
    """Capability-limited read/write view over one ArtifactStore.

    Components receive this object instead of the Store.  They can inspect the
    immutable DAG and commit only artifact/event types in the store-issued
    capability.  There is intentionally no API for selecting a producer name.
    """

    __slots__ = ("_authorization", "_capability", "_store")

    def __init__(
        self,
        store: ArtifactStore,
        capability: ProducerCapability,
        authorization: object,
    ) -> None:
        self._store = store
        self._capability = capability
        self._authorization = authorization

    @property
    def capability(self) -> ProducerCapability:
        return self._capability

    @property
    def producer(self) -> str:
        return self._capability.producer

    def put_json(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        value: BaseModel | Mapping[str, Any] | Sequence[Any],
        dependencies: Iterable[ArtifactRef] = (),
    ) -> ArtifactRef:
        json_value: Any
        if isinstance(value, BaseModel):
            json_value = value.model_dump(mode="json", by_alias=True, exclude_none=False)
        else:
            json_value = value
        self._store._assert_publishable_json(json_value)
        try:
            content = canonical_json_bytes(json_value)
        except (TypeError, ValueError) as exc:
            raise UnsafeArtifactError(f"value is not canonical JSON: {exc}") from exc
        return self._store._commit(
            capability=self._capability,
            authorization=self._authorization,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=content,
            media_type="application/json",
            dependencies=dependencies,
        )

    def put_blob(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        content: bytes,
        media_type: str,
        dependencies: Iterable[ArtifactRef] = (),
    ) -> ArtifactRef:
        if not isinstance(content, bytes):
            raise TypeError("blob content must be bytes")
        return self._store._commit(
            capability=self._capability,
            authorization=self._authorization,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content=content,
            media_type=media_type,
            dependencies=dependencies,
        )

    def record_event(
        self,
        *,
        event_type: str,
        subject_ref: ArtifactRef,
        related_refs: Iterable[ArtifactRef] = (),
        reason_code: str | None = None,
        details: Iterable[KeyValue] = (),
    ) -> ArtifactEvent:
        return self._store._record_event(
            capability=self._capability,
            authorization=self._authorization,
            event_type=event_type,
            subject_ref=subject_ref,
            related_refs=related_refs,
            reason_code=reason_code,
            details=details,
            enforce_scope=True,
        )

    @overload
    def get_json(self, ref: ArtifactRef, model: type[TModel]) -> TModel: ...

    @overload
    def get_json(self, ref: ArtifactRef, model: None = None) -> Any: ...

    def get_json(self, ref: ArtifactRef, model: type[TModel] | None = None) -> TModel | Any:
        return self._store.get_json(ref, model)

    def get_blob(self, ref: ArtifactRef) -> bytes:
        return self._store.get_blob(ref)

    def require_exact_json(
        self,
        ref: ArtifactRef,
        value: BaseModel,
        *,
        artifact_types: Iterable[str] = (),
    ) -> None:
        self._store.require_exact_json(ref, value, artifact_types=artifact_types)

    def get_revision(self, ref: ArtifactRef) -> ArtifactRevision:
        return self._store.get_revision(ref)

    def dependencies(self, ref: ArtifactRef) -> tuple[ArtifactRef, ...]:
        return self._store.dependencies(ref)

    def dependents(self, ref: ArtifactRef) -> tuple[ArtifactRef, ...]:
        return self._store.dependents(ref)

    def list_revisions(self, artifact_id: str | None = None) -> tuple[ArtifactRef, ...]:
        return self._store.list_revisions(artifact_id)

    def list_events(self) -> tuple[ArtifactEvent, ...]:
        return self._store.list_events()

    def list_events_for_run(
        self,
        run_id: str,
        *,
        anchor_artifact_ids: Iterable[str] = (),
    ) -> tuple[ArtifactEvent, ...]:
        return self._store.list_events_for_run(
            run_id,
            anchor_artifact_ids=anchor_artifact_ids,
        )


class ArtifactStore:
    """Filesystem-backed immutable revision, blob, edge, and event store.

    Paths are derived only from validated hashes.  Files are committed with a
    hard-link create operation, which is atomic and cannot replace an existing
    destination.  Every read checks both the revision identity and blob hash.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        known_secret_canaries: Sequence[str | bytes] = (),
    ) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise UnsafeArtifactError("artifact store root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise UnsafeArtifactError("artifact store root must be a real directory")
        self._root = requested.resolve(strict=True)
        canaries: set[bytes] = set()
        for raw in known_secret_canaries:
            value = raw.encode("utf-8") if isinstance(raw, str) else raw
            if not isinstance(value, bytes) or not 4 <= len(value) <= 8192:
                raise ValueError("secret canaries must contain 4..8192 bytes")
            canaries.add(value)
        self._secret_canaries = tuple(sorted(canaries))
        for name in ("blobs", "revisions", "events", "indexes", "tmp"):
            self._ensure_directory(self._safe_path(name))
        self._provenance_key = self._load_or_create_provenance_key()
        self._projection_lock = threading.RLock()
        self._projection = self._open_projection()
        self._capability_issuance_sealed = False
        self._writer_authorizations: dict[str, set[object]] = {}
        # A Store instance is the single authenticated view used by one controller
        # process.  Building this index once avoids re-reading every immutable
        # revision manifest for each exact-artifact lookup during checkpoint resume.
        # Commits made through this Store extend the same verified view below.
        self._revision_refs_by_artifact: dict[str, tuple[ArtifactRef, ...]] | None = None
        self._all_revision_refs: tuple[ArtifactRef, ...] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def _open_projection(self) -> sqlite3.Connection:
        """Open a rebuildable, HMAC-checked lookup projection.

        Immutable revision/event files remain authoritative. The projection
        only avoids reparsing the entire history for exact-id and per-run
        reads; every returned row is bound to this store's provenance key.
        """

        path = self._safe_path("indexes", "projection.sqlite")
        if path.exists() and path.is_symlink():
            raise UnsafeArtifactError("artifact projection cannot be a symlink")
        connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
        os.chmod(path, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projection_state(
                kind TEXT PRIMARY KEY,
                item_count INTEGER NOT NULL,
                latest_name TEXT NOT NULL,
                attestation TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revision_rows(
                revision_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                ref_json TEXT NOT NULL,
                attestation TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS revision_artifact_idx
                ON revision_rows(artifact_id, revision_id);
            CREATE TABLE IF NOT EXISTS event_rows(
                filename TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                attestation TEXT NOT NULL
            );
            """
        )
        connection.commit()
        return connection

    def _projection_state(self, kind: str) -> tuple[int, str] | None:
        row = self._projection.execute(
            "SELECT item_count, latest_name, attestation FROM projection_state WHERE kind = ?",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        body = {
            "kind": kind,
            "item_count": int(row["item_count"]),
            "latest_name": str(row["latest_name"]),
        }
        expected = self._attest("artifact-projection-state", body)
        if not hmac.compare_digest(str(row["attestation"]), expected):
            return None
        return int(row["item_count"]), str(row["latest_name"])

    def _set_projection_state(self, kind: str, item_count: int, latest_name: str) -> None:
        body = {
            "kind": kind,
            "item_count": item_count,
            "latest_name": latest_name,
        }
        self._projection.execute(
            """
            INSERT OR REPLACE INTO projection_state(kind, item_count, latest_name, attestation)
            VALUES (?, ?, ?, ?)
            """,
            (kind, item_count, latest_name, self._attest("artifact-projection-state", body)),
        )

    def _actual_projection_extent(self, kind: str) -> tuple[int, str]:
        if kind == "events":
            directory = self._safe_path("events")
            names: list[str] = []
            for path in directory.iterdir():
                if path.is_symlink():
                    raise UnsafeArtifactError(f"symlink found in event store: {path}")
                if path.is_file() and path.suffix == ".json":
                    names.append(path.name)
            return len(names), max(names, default="")
        if kind != "revisions":
            raise ValueError("unknown artifact projection kind")
        directory = self._safe_path("revisions", "sha256")
        names = []
        if directory.exists():
            for prefix in directory.iterdir():
                if prefix.is_symlink():
                    raise UnsafeArtifactError(f"symlink found in revision store: {prefix}")
                if not prefix.is_dir():
                    continue
                for path in prefix.iterdir():
                    if path.is_symlink():
                        raise UnsafeArtifactError(f"symlink found in revision store: {path}")
                    if path.is_file() and path.suffix == ".json":
                        names.append(f"{prefix.name}/{path.name}")
        return len(names), max(names, default="")

    def _ensure_projection(self, kind: str) -> None:
        with self._projection_lock:
            actual = self._actual_projection_extent(kind)
            state = self._projection_state(kind)
            table = "event_rows" if kind == "events" else "revision_rows"
            row_count = int(
                self._projection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 - fixed internal table allowlist
            )
            if state == actual and row_count == actual[0]:
                return
            self._rebuild_projection(kind)

    def _rebuild_projection(self, kind: str) -> None:
        if kind == "revisions":
            self._projection.execute("DELETE FROM revision_rows")
            count = 0
            latest = ""
            for revision in self._iter_revisions():
                self._insert_revision_projection(revision.ref)
                count += 1
                name = self._revision_projection_name(revision.ref)
                latest = max(latest, name)
        elif kind == "events":
            self._projection.execute("DELETE FROM event_rows")
            count = 0
            latest = ""
            directory = self._safe_path("events")
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                if path.is_symlink():
                    raise UnsafeArtifactError(f"symlink found in event store: {path}")
                if not path.is_file() or path.suffix != ".json":
                    continue
                event = self._read_event_path(path)
                self._insert_event_projection(path.name, event)
                count += 1
                latest = path.name
        else:
            raise ValueError("unknown artifact projection kind")
        self._set_projection_state(kind, count, latest)
        self._projection.commit()

    @staticmethod
    def _revision_projection_name(ref: ArtifactRef) -> str:
        digest = ref.revision_id.removeprefix("sha256:")
        return f"{digest[:2]}/{digest}.json"

    def _insert_revision_projection(self, ref: ArtifactRef) -> bool:
        ref_json = canonical_json_bytes(ref).decode("utf-8")
        body = {
            "revision_id": ref.revision_id,
            "artifact_id": ref.artifact_id,
            "ref_json": ref_json,
        }
        cursor = self._projection.execute(
            """
            INSERT OR IGNORE INTO revision_rows(revision_id, artifact_id, ref_json, attestation)
            VALUES (?, ?, ?, ?)
            """,
            (
                ref.revision_id,
                ref.artifact_id,
                ref_json,
                self._attest("artifact-projection-revision", body),
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _event_scope_keys(event: ArtifactEvent) -> tuple[str, ...]:
        scopes: set[str] = set()
        for ref in (event.subject_ref, *event.related_refs):
            scopes.add(f"artifact:{ref.artifact_id}")
            if ref.artifact_id.startswith("run:"):
                parts = ref.artifact_id.split(":", 2)
                if len(parts) >= 2 and parts[1]:
                    scopes.add(f"run-scope:run:{parts[1]}")
        return tuple(sorted(scopes))

    def _insert_event_projection(self, filename: str, event: ArtifactEvent) -> bool:
        scopes_json = canonical_json_bytes(self._event_scope_keys(event)).decode("utf-8")
        body = {
            "filename": filename,
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            "scopes_json": scopes_json,
        }
        cursor = self._projection.execute(
            """
            INSERT OR IGNORE INTO event_rows(
                filename, event_id, occurred_at, scopes_json, attestation
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                filename,
                event.event_id,
                event.occurred_at.isoformat(),
                scopes_json,
                self._attest("artifact-projection-event", body),
            ),
        )
        return cursor.rowcount == 1

    @property
    def capability_issuance_sealed(self) -> bool:
        return self._capability_issuance_sealed

    def seal_capability_issuance(self) -> None:
        """Irreversibly close producer-capability issuance for this Store instance."""

        self._capability_issuance_sealed = True

    def issue_writer(
        self,
        *,
        producer: str,
        allowed_artifact_types: Iterable[str] = (),
        allowed_artifact_type_prefixes: Iterable[str] = (),
        allowed_artifact_id_prefixes: Iterable[str] = (),
        allowed_event_types: Iterable[str] = (),
        allowed_event_type_prefixes: Iterable[str] = (),
    ) -> ArtifactWriter:
        """Issue one deterministic, least-privilege producer handle.

        Reissuing the same scope after a process restart yields the same
        capability id, preserving idempotent revision identities.  Expanding
        the scope produces a different capability and therefore a different
        revision identity even for identical content.
        """

        if self._capability_issuance_sealed:
            raise ArtifactStoreError("producer capability issuance is sealed")
        self._validate_identifier(producer, "producer")
        artifact_types = self._normalise_scope_values(
            allowed_artifact_types,
            label="allowed_artifact_types",
            identifiers=True,
        )
        artifact_type_prefixes = self._normalise_scope_values(
            allowed_artifact_type_prefixes,
            label="allowed_artifact_type_prefixes",
            identifiers=False,
        )
        artifact_id_prefixes = self._normalise_scope_values(
            allowed_artifact_id_prefixes,
            label="allowed_artifact_id_prefixes",
            identifiers=False,
        )
        event_types = self._normalise_scope_values(
            allowed_event_types,
            label="allowed_event_types",
            identifiers=True,
        )
        event_type_prefixes = self._normalise_scope_values(
            allowed_event_type_prefixes,
            label="allowed_event_type_prefixes",
            identifiers=False,
        )
        if not any(
            (artifact_types, artifact_type_prefixes, event_types, event_type_prefixes)
        ):
            raise ValueError("producer capability must authorize at least one artifact or event")
        scope = {
            "producer": producer,
            "allowed_artifact_types": artifact_types,
            "allowed_artifact_type_prefixes": artifact_type_prefixes,
            "allowed_artifact_id_prefixes": artifact_id_prefixes,
            "allowed_event_types": event_types,
            "allowed_event_type_prefixes": event_type_prefixes,
        }
        scope_digest = sha256_digest(canonical_json_bytes(scope)).removeprefix("sha256:")
        capability_id = f"cap:{scope_digest}"
        unsigned = {"capability_id": capability_id, **scope}
        capability = ProducerCapability(
            capability_id=capability_id,
            producer=producer,
            allowed_artifact_types=artifact_types,
            allowed_artifact_type_prefixes=artifact_type_prefixes,
            allowed_artifact_id_prefixes=artifact_id_prefixes,
            allowed_event_types=event_types,
            allowed_event_type_prefixes=event_type_prefixes,
            attestation=self._attest("producer-capability", unsigned),
        )
        self._verify_capability(capability)
        authorization = object()
        self._writer_authorizations.setdefault(capability.capability_id, set()).add(
            authorization
        )
        return ArtifactWriter(self, capability, authorization)

    @overload
    def get_json(self, ref: ArtifactRef, model: type[TModel]) -> TModel: ...

    @overload
    def get_json(self, ref: ArtifactRef, model: None = None) -> Any: ...

    def get_json(self, ref: ArtifactRef, model: type[TModel] | None = None) -> TModel | Any:
        revision = self.get_revision(ref)
        if revision.ref.media_type != "application/json":
            raise ArtifactStoreError(f"artifact {ref.revision_id} is not JSON")
        raw = self._read_blob(revision.ref)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArtifactIntegrityError(f"stored JSON is invalid: {ref.revision_id}") from exc
        if model is None:
            return value
        return model.model_validate_json(raw)

    def get_blob(self, ref: ArtifactRef) -> bytes:
        revision = self.get_revision(ref)
        return self._read_blob(revision.ref)

    def require_exact_json(
        self,
        ref: ArtifactRef,
        value: BaseModel,
        *,
        artifact_types: Iterable[str] = (),
    ) -> None:
        """Fail closed unless ``ref`` stores this exact typed object.

        Component APIs deliberately accept both an immutable ref and a parsed
        object for efficiency.  Every trust boundary must call this method so
        a caller cannot pair object B with the provenance of object A.
        """

        allowed = frozenset(artifact_types)
        if allowed and ref.artifact_type not in allowed:
            raise ArtifactIntegrityError(
                f"artifact type {ref.artifact_type!r} is not one of {sorted(allowed)!r}"
            )
        expected_hash = sha256_digest(canonical_json_bytes(value))
        if ref.content_hash != expected_hash:
            raise ArtifactIntegrityError(
                f"object content does not match artifact ref: {ref.revision_id}"
            )
        stored = self.get_json(ref, type(value))
        if stored != value:
            raise ArtifactIntegrityError(
                f"stored object differs from supplied object: {ref.revision_id}"
            )

    def get_revision(self, ref: ArtifactRef) -> ArtifactRevision:
        return self._get_revision(ref, set(), {})

    def _get_revision(
        self,
        ref: ArtifactRef,
        stack: set[str],
        verified: dict[str, ArtifactRevision],
    ) -> ArtifactRevision:
        if ref.revision_id in stack:
            raise ArtifactIntegrityError(f"dependency cycle detected at {ref.revision_id}")
        cached = verified.get(ref.revision_id)
        if cached is not None:
            if cached.ref != ref:
                raise ArtifactIntegrityError(
                    f"revision reference mismatch: {ref.revision_id}"
                )
            return cached
        stack.add(ref.revision_id)
        path = self._revision_path(ref.revision_id)
        raw = self._read_file(path, missing_message=f"revision not found: {ref.revision_id}")
        try:
            revision = ArtifactRevision.model_validate_json(raw)
        except Exception as exc:
            raise ArtifactIntegrityError(f"invalid revision manifest: {ref.revision_id}") from exc
        if revision.ref != ref:
            raise ArtifactIntegrityError(f"revision reference mismatch: {ref.revision_id}")
        self._verify_capability(revision.capability)
        expected_id = self._revision_id(
            revision.ref,
            revision.dependency_refs,
            revision.capability,
        )
        if expected_id != ref.revision_id:
            raise ArtifactIntegrityError(f"revision identity mismatch: {ref.revision_id}")
        expected_attestation = self._revision_attestation(
            revision.ref,
            revision.dependency_refs,
            revision.capability,
        )
        if not hmac.compare_digest(revision.producer_attestation, expected_attestation):
            raise ArtifactIntegrityError(
                f"revision producer attestation mismatch: {ref.revision_id}"
            )
        self._read_blob(ref)
        for dependency_ref in revision.dependency_refs:
            self._get_revision(dependency_ref, stack, verified)
        stack.remove(ref.revision_id)
        verified[ref.revision_id] = revision
        return revision

    def dependencies(self, ref: ArtifactRef) -> tuple[ArtifactRef, ...]:
        return self.get_revision(ref).dependency_refs

    def dependents(self, ref: ArtifactRef) -> tuple[ArtifactRef, ...]:
        matches: list[ArtifactRef] = []
        for revision in self._iter_revisions():
            if ref in revision.dependency_refs:
                matches.append(revision.ref)
        return tuple(sorted(matches, key=lambda item: (item.artifact_id, item.revision_id)))

    def list_revisions(self, artifact_id: str | None = None) -> tuple[ArtifactRef, ...]:
        if artifact_id is not None:
            self._validate_identifier(artifact_id, "artifact_id")
            if self._revision_refs_by_artifact is not None:
                cached = self._revision_refs_by_artifact.get(artifact_id)
                if cached is not None:
                    return cached
            self._ensure_projection("revisions")
            refs: list[ArtifactRef] = []
            with self._projection_lock:
                rows = self._projection.execute(
                    """
                    SELECT revision_id, artifact_id, ref_json, attestation
                    FROM revision_rows WHERE artifact_id = ? ORDER BY revision_id
                    """,
                    (artifact_id,),
                ).fetchall()
            for row in rows:
                body = {
                    "revision_id": str(row["revision_id"]),
                    "artifact_id": str(row["artifact_id"]),
                    "ref_json": str(row["ref_json"]),
                }
                expected = self._attest("artifact-projection-revision", body)
                if not hmac.compare_digest(str(row["attestation"]), expected):
                    raise ArtifactIntegrityError("revision projection row attestation mismatch")
                try:
                    ref = ArtifactRef.model_validate_json(body["ref_json"])
                except Exception as exc:
                    raise ArtifactIntegrityError(
                        "revision projection contains an invalid ref"
                    ) from exc
                if ref.revision_id != body["revision_id"] or ref.artifact_id != artifact_id:
                    raise ArtifactIntegrityError("revision projection identity mismatch")
                refs.append(ref)
            result = tuple(refs)
            if self._revision_refs_by_artifact is None:
                self._revision_refs_by_artifact = {}
            self._revision_refs_by_artifact[artifact_id] = result
            return result
        if self._all_revision_refs is None:
            self._ensure_projection("revisions")
            with self._projection_lock:
                rows = self._projection.execute(
                    """
                    SELECT revision_id, artifact_id, ref_json, attestation
                    FROM revision_rows ORDER BY artifact_id, revision_id
                    """
                ).fetchall()
            projected: list[ArtifactRef] = []
            for row in rows:
                body = {
                    "revision_id": str(row["revision_id"]),
                    "artifact_id": str(row["artifact_id"]),
                    "ref_json": str(row["ref_json"]),
                }
                expected = self._attest("artifact-projection-revision", body)
                if not hmac.compare_digest(str(row["attestation"]), expected):
                    raise ArtifactIntegrityError("revision projection row attestation mismatch")
                try:
                    ref = ArtifactRef.model_validate_json(body["ref_json"])
                except Exception as exc:
                    raise ArtifactIntegrityError(
                        "revision projection contains an invalid ref"
                    ) from exc
                if (
                    ref.revision_id != body["revision_id"]
                    or ref.artifact_id != body["artifact_id"]
                ):
                    raise ArtifactIntegrityError("revision projection identity mismatch")
                projected.append(ref)
            all_refs = tuple(projected)
            grouped: dict[str, list[ArtifactRef]] = {}
            for ref in all_refs:
                grouped.setdefault(ref.artifact_id, []).append(ref)
            self._revision_refs_by_artifact = {
                key: tuple(value) for key, value in grouped.items()
            }
            self._all_revision_refs = all_refs
        assert self._all_revision_refs is not None
        return self._all_revision_refs

    def _record_event(
        self,
        *,
        capability: ProducerCapability,
        authorization: object,
        event_type: str,
        subject_ref: ArtifactRef,
        related_refs: Iterable[ArtifactRef] = (),
        reason_code: str | None = None,
        details: Iterable[KeyValue] = (),
        enforce_scope: bool,
    ) -> ArtifactEvent:
        self._validate_identifier(event_type, "event_type")
        self._verify_capability(capability)
        self._verify_writer_authorization(capability, authorization)
        if enforce_scope:
            self._authorize_event(capability, event_type)
        if reason_code is not None:
            self._validate_identifier(reason_code, "reason_code")
        self.get_revision(subject_ref)
        related = self._normalise_refs(related_refs, verify=True)
        detail_tuple = tuple(details)
        for item in detail_tuple:
            if item.key.strip().lower() in _FORBIDDEN_VALUE_KEYS:
                raise UnsafeArtifactError(f"sensitive event detail is prohibited: {item.key}")
        self._assert_publishable_json(
            [item.model_dump(mode="json", exclude_none=False) for item in detail_tuple]
        )
        now = datetime.now(UTC)
        digest = self._event_digest(
            event_type=event_type,
            occurred_at=now,
            subject_ref=subject_ref,
            related_refs=related,
            capability=capability,
            reason_code=reason_code,
            details=detail_tuple,
        )
        event_attestation = self._attest("artifact-event", digest)
        event = ArtifactEvent(
            event_id=f"evt_{digest}",
            event_type=event_type,
            occurred_at=now,
            subject_ref=subject_ref,
            related_refs=related,
            capability=capability,
            reason_code=reason_code,
            details=detail_tuple,
            producer_attestation=event_attestation,
        )
        name = f"{time.time_ns():020d}-{digest}.json"
        event_bytes = event.stable_json_bytes()
        self._assert_safe_content(event_bytes)
        created = self._atomic_create(self._safe_path("events", name), event_bytes)
        if created:
            self._append_event_projection(name, event)
        return event

    def list_events(self) -> tuple[ArtifactEvent, ...]:
        directory = self._safe_path("events")
        events: list[ArtifactEvent] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.is_symlink():
                raise UnsafeArtifactError(f"symlink found in event store: {path}")
            if not path.is_file() or path.suffix != ".json":
                continue
            events.append(self._read_event_path(path))
        return tuple(events)

    def list_events_for_run(
        self,
        run_id: str,
        *,
        anchor_artifact_ids: Iterable[str] = (),
    ) -> tuple[ArtifactEvent, ...]:
        """Read one run's events without reparsing unrelated immutable history."""

        self._validate_identifier(run_id, "run_id")
        anchors = tuple(anchor_artifact_ids)
        for artifact_id in anchors:
            self._validate_identifier(artifact_id, "anchor_artifact_id")
        wanted = {f"run-scope:{run_id}", *(f"artifact:{item}" for item in anchors)}
        self._ensure_projection("events")
        with self._projection_lock:
            rows = self._projection.execute(
                """
                SELECT filename, event_id, occurred_at, scopes_json, attestation
                FROM event_rows ORDER BY filename
                """
            ).fetchall()
        selected: list[ArtifactEvent] = []
        for row in rows:
            body = {
                "filename": str(row["filename"]),
                "event_id": str(row["event_id"]),
                "occurred_at": str(row["occurred_at"]),
                "scopes_json": str(row["scopes_json"]),
            }
            expected = self._attest("artifact-projection-event", body)
            if not hmac.compare_digest(str(row["attestation"]), expected):
                raise ArtifactIntegrityError("event projection row attestation mismatch")
            try:
                scopes = json.loads(body["scopes_json"])
            except json.JSONDecodeError as exc:
                raise ArtifactIntegrityError("event projection scopes are invalid") from exc
            if (
                not isinstance(scopes, list)
                or any(not isinstance(item, str) for item in scopes)
                or tuple(scopes) != tuple(sorted(set(scopes)))
            ):
                raise ArtifactIntegrityError("event projection scopes are not canonical")
            if wanted.isdisjoint(scopes):
                continue
            event = self._read_event_path(self._safe_path("events", body["filename"]))
            if event.event_id != body["event_id"] or event.occurred_at.isoformat() != body[
                "occurred_at"
            ]:
                raise ArtifactIntegrityError("event projection identity mismatch")
            if self._event_scope_keys(event) != tuple(scopes):
                raise ArtifactIntegrityError("event projection scope mismatch")
            selected.append(event)
        return tuple(selected)

    def _read_event_path(self, path: Path) -> ArtifactEvent:
        raw = self._read_file(path, missing_message=f"event disappeared: {path.name}")
        try:
            event = ArtifactEvent.model_validate_json(raw)
        except Exception as exc:
            raise ArtifactIntegrityError(f"invalid event: {path.name}") from exc
        digest = self._event_digest(
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            subject_ref=event.subject_ref,
            related_refs=event.related_refs,
            capability=event.capability,
            reason_code=event.reason_code,
            details=event.details,
        )
        if event.event_id != f"evt_{digest}" or not path.name.endswith(f"-{digest}.json"):
            raise ArtifactIntegrityError(f"event identity mismatch: {path.name}")
        self._verify_capability(event.capability)
        expected_attestation = self._attest("artifact-event", digest)
        if not hmac.compare_digest(event.producer_attestation, expected_attestation):
            raise ArtifactIntegrityError(f"event producer attestation mismatch: {path.name}")
        return event

    @staticmethod
    def _event_digest(
        *,
        event_type: str,
        occurred_at: datetime,
        subject_ref: ArtifactRef,
        related_refs: tuple[ArtifactRef, ...],
        capability: ProducerCapability,
        reason_code: str | None,
        details: tuple[KeyValue, ...],
    ) -> str:
        body = {
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "subject_revision_id": subject_ref.revision_id,
            "related_revision_ids": [item.revision_id for item in related_refs],
            "capability": capability.model_dump(mode="json", exclude_none=False),
            "reason_code": reason_code,
            "details": [item.model_dump(mode="json", exclude_none=False) for item in details],
        }
        return sha256_digest(canonical_json_bytes(body)).removeprefix("sha256:")

    def _commit(
        self,
        *,
        capability: ProducerCapability,
        authorization: object,
        artifact_id: str,
        artifact_type: str,
        content: bytes,
        media_type: str,
        dependencies: Iterable[ArtifactRef],
    ) -> ArtifactRef:
        self._validate_identifier(artifact_id, "artifact_id")
        self._validate_artifact_type(artifact_type)
        self._verify_capability(capability)
        self._verify_writer_authorization(capability, authorization)
        self._authorize_artifact(capability, artifact_id, artifact_type)
        if not media_type or any(character.isspace() for character in media_type):
            raise UnsafeArtifactError("media_type must be a non-empty MIME type without whitespace")
        self._assert_safe_content(content)
        dependency_refs = self._normalise_refs(dependencies, verify=True)
        content_hash = sha256_digest(content)
        blob_path = self._blob_path(content_hash)
        self._atomic_create(blob_path, content)

        provisional = ArtifactRef(
            artifact_id=artifact_id,
            revision_id="sha256:" + "0" * 64,
            artifact_type=artifact_type,
            content_hash=content_hash,
            media_type=media_type,
            size_bytes=len(content),
        )
        revision_id = self._revision_id(provisional, dependency_refs, capability)
        ref = provisional.model_copy(update={"revision_id": revision_id})
        revision = ArtifactRevision(
            ref=ref,
            dependency_refs=dependency_refs,
            capability=capability,
            producer_attestation=self._revision_attestation(
                ref,
                dependency_refs,
                capability,
            ),
        )
        created = self._atomic_create(
            self._revision_path(revision_id), revision.stable_json_bytes()
        )
        if created:
            self._append_revision_projection(ref)
            self._remember_revision_ref(ref)
            self._record_event(
                capability=capability,
                authorization=authorization,
                event_type="artifact_revision_committed",
                subject_ref=ref,
                related_refs=dependency_refs,
                enforce_scope=False,
            )
        return ref

    def _append_revision_projection(self, ref: ArtifactRef) -> None:
        with self._projection_lock:
            previous_state = self._projection_state("revisions")
            previous_count = int(
                self._projection.execute("SELECT COUNT(*) FROM revision_rows").fetchone()[0]
            )
            inserted = self._insert_revision_projection(ref)
            if inserted and previous_state is not None and previous_state[0] == previous_count:
                self._set_projection_state(
                    "revisions",
                    previous_count + 1,
                    max(previous_state[1], self._revision_projection_name(ref)),
                )
            else:
                self._projection.execute(
                    "DELETE FROM projection_state WHERE kind = 'revisions'"
                )
            self._projection.commit()

    def _append_event_projection(self, filename: str, event: ArtifactEvent) -> None:
        with self._projection_lock:
            previous_state = self._projection_state("events")
            previous_count = int(
                self._projection.execute("SELECT COUNT(*) FROM event_rows").fetchone()[0]
            )
            inserted = self._insert_event_projection(filename, event)
            if inserted and previous_state is not None and previous_state[0] == previous_count:
                self._set_projection_state(
                    "events",
                    previous_count + 1,
                    max(previous_state[1], filename),
                )
            else:
                self._projection.execute("DELETE FROM projection_state WHERE kind = 'events'")
            self._projection.commit()

    def _remember_revision_ref(self, ref: ArtifactRef) -> None:
        """Extend an already-built authenticated in-process revision index."""

        if self._revision_refs_by_artifact is not None:
            existing = self._revision_refs_by_artifact.get(ref.artifact_id, ())
            if ref not in existing:
                self._revision_refs_by_artifact[ref.artifact_id] = tuple(
                    sorted((*existing, ref), key=lambda item: item.revision_id)
                )
        if self._all_revision_refs is not None and ref not in self._all_revision_refs:
            self._all_revision_refs = tuple(
                sorted(
                    (*self._all_revision_refs, ref),
                    key=lambda item: (item.artifact_id, item.revision_id),
                )
            )

    def _normalise_refs(
        self, refs: Iterable[ArtifactRef], *, verify: bool
    ) -> tuple[ArtifactRef, ...]:
        result = tuple(sorted(tuple(refs), key=lambda item: (item.artifact_id, item.revision_id)))
        identities = [item.revision_id for item in result]
        if len(set(identities)) != len(identities):
            raise ArtifactStoreError("dependency and related refs must be unique")
        if verify:
            stack: set[str] = set()
            verified: dict[str, ArtifactRevision] = {}
            for ref in result:
                self._get_revision(ref, stack, verified)
        return result

    @staticmethod
    def _revision_id(
        ref: ArtifactRef,
        dependencies: tuple[ArtifactRef, ...],
        capability: ProducerCapability,
    ) -> str:
        identity = {
            "schema_version": "v2",
            "artifact_id": ref.artifact_id,
            "artifact_type": ref.artifact_type,
            "content_hash": ref.content_hash,
            "media_type": ref.media_type,
            "size_bytes": ref.size_bytes,
            "dependency_revision_ids": [item.revision_id for item in dependencies],
            "capability": capability.model_dump(mode="json", exclude_none=False),
        }
        return sha256_digest(canonical_json_bytes(identity))

    def _iter_revisions(self) -> Iterable[ArtifactRevision]:
        directory = self._safe_path("revisions", "sha256")
        if not directory.exists():
            return
        for prefix in sorted(directory.iterdir(), key=lambda item: item.name):
            if prefix.is_symlink():
                raise UnsafeArtifactError(f"symlink found in revision store: {prefix}")
            if not prefix.is_dir():
                continue
            for path in sorted(prefix.iterdir(), key=lambda item: item.name):
                if path.is_symlink():
                    raise UnsafeArtifactError(f"symlink found in revision store: {path}")
                if not path.is_file() or path.suffix != ".json":
                    continue
                raw = self._read_file(path, missing_message=f"revision disappeared: {path.name}")
                try:
                    revision = ArtifactRevision.model_validate_json(raw)
                except Exception as exc:
                    raise ArtifactIntegrityError(f"invalid revision manifest: {path.name}") from exc
                expected_path = self._revision_path(revision.ref.revision_id)
                if expected_path != path:
                    raise ArtifactIntegrityError(f"revision stored at wrong path: {path}")
                self._verify_capability(revision.capability)
                if (
                    self._revision_id(
                        revision.ref,
                        revision.dependency_refs,
                        revision.capability,
                    )
                    != revision.ref.revision_id
                ):
                    raise ArtifactIntegrityError(f"invalid revision identity: {path.name}")
                expected_attestation = self._revision_attestation(
                    revision.ref,
                    revision.dependency_refs,
                    revision.capability,
                )
                if not hmac.compare_digest(
                    revision.producer_attestation,
                    expected_attestation,
                ):
                    raise ArtifactIntegrityError(
                        f"invalid revision producer attestation: {path.name}"
                    )
                yield revision

    def _read_blob(self, ref: ArtifactRef) -> bytes:
        path = self._blob_path(ref.content_hash)
        content = self._read_file(path, missing_message=f"blob not found: {ref.content_hash}")
        if len(content) != ref.size_bytes:
            raise ArtifactIntegrityError(f"blob size mismatch: {ref.content_hash}")
        if sha256_digest(content) != ref.content_hash:
            raise ArtifactIntegrityError(f"blob hash mismatch: {ref.content_hash}")
        return content

    def _load_or_create_provenance_key(self) -> bytes:
        path = self._safe_path(_PROVENANCE_KEY_NAME)
        if not path.exists():
            value = secrets.token_bytes(_PROVENANCE_KEY_BYTES)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                try:
                    view = memoryview(value)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise ArtifactStoreError("failed to persist provenance key")
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                directory_fd = os.open(self._root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        if path.is_symlink():
            raise UnsafeArtifactError("provenance key cannot be a symlink")
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ArtifactStoreError("provenance key disappeared during initialization") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise UnsafeArtifactError("provenance key must be an independent regular file")
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UnsafeArtifactError("provenance key permissions must be exactly 0600")
        value = self._read_file(path, missing_message="provenance key is missing")
        if len(value) != _PROVENANCE_KEY_BYTES:
            raise ArtifactIntegrityError("provenance key has an invalid size")
        return value

    @classmethod
    def _normalise_scope_values(
        cls,
        values: Iterable[str],
        *,
        label: str,
        identifiers: bool,
    ) -> tuple[str, ...]:
        result = tuple(sorted(set(values)))
        for value in result:
            if identifiers:
                cls._validate_identifier(value, label)
            elif _SCOPE_PREFIX_PATTERN.fullmatch(value) is None:
                raise ValueError(f"invalid {label}: {value!r}")
        return result

    @staticmethod
    def _capability_unsigned(capability: ProducerCapability) -> dict[str, Any]:
        value = capability.model_dump(mode="json", exclude_none=False)
        value.pop("schema_version")
        value.pop("attestation")
        return value

    def _verify_capability(self, capability: ProducerCapability) -> None:
        unsigned = self._capability_unsigned(capability)
        scope = {key: value for key, value in unsigned.items() if key != "capability_id"}
        expected_id = (
            "cap:"
            + sha256_digest(canonical_json_bytes(scope)).removeprefix("sha256:")
        )
        if capability.capability_id != expected_id:
            raise ArtifactIntegrityError("producer capability identity mismatch")
        for key in (
            "allowed_artifact_types",
            "allowed_event_types",
        ):
            values = tuple(unsigned[key])
            if values != self._normalise_scope_values(values, label=key, identifiers=True):
                raise ArtifactIntegrityError(f"producer capability {key} is not canonical")
        for key in (
            "allowed_artifact_type_prefixes",
            "allowed_artifact_id_prefixes",
            "allowed_event_type_prefixes",
        ):
            values = tuple(unsigned[key])
            if values != self._normalise_scope_values(values, label=key, identifiers=False):
                raise ArtifactIntegrityError(f"producer capability {key} is not canonical")
        if _ATTESTATION_PATTERN.fullmatch(capability.attestation) is None:
            raise ArtifactIntegrityError("producer capability attestation is malformed")
        expected = self._attest("producer-capability", unsigned)
        if not hmac.compare_digest(capability.attestation, expected):
            raise ArtifactIntegrityError("producer capability attestation mismatch")

    def _verify_writer_authorization(
        self,
        capability: ProducerCapability,
        authorization: object,
    ) -> None:
        registered = self._writer_authorizations.get(capability.capability_id, set())
        if not any(item is authorization for item in registered):
            raise ArtifactStoreError("producer capability has no active writer authorization")

    @staticmethod
    def _authorize_artifact(
        capability: ProducerCapability,
        artifact_id: str,
        artifact_type: str,
    ) -> None:
        allowed_type = artifact_type in capability.allowed_artifact_types or any(
            artifact_type.startswith(prefix)
            for prefix in capability.allowed_artifact_type_prefixes
        )
        if not allowed_type:
            raise UnsafeArtifactError(
                f"producer {capability.producer!r} cannot write artifact type "
                f"{artifact_type!r}"
            )
        if capability.allowed_artifact_id_prefixes and not any(
            artifact_id.startswith(prefix) for prefix in capability.allowed_artifact_id_prefixes
        ):
            raise UnsafeArtifactError(
                f"producer {capability.producer!r} cannot write artifact id {artifact_id!r}"
            )

    @staticmethod
    def _authorize_event(capability: ProducerCapability, event_type: str) -> None:
        allowed = event_type in capability.allowed_event_types or any(
            event_type.startswith(prefix) for prefix in capability.allowed_event_type_prefixes
        )
        if not allowed:
            raise UnsafeArtifactError(
                f"producer {capability.producer!r} cannot record event type {event_type!r}"
            )

    def _revision_attestation(
        self,
        ref: ArtifactRef,
        dependencies: tuple[ArtifactRef, ...],
        capability: ProducerCapability,
    ) -> str:
        body = {
            "ref": ref.model_dump(mode="json", exclude_none=False),
            "dependency_refs": [
                item.model_dump(mode="json", exclude_none=False) for item in dependencies
            ],
            "capability": capability.model_dump(mode="json", exclude_none=False),
        }
        return self._attest("artifact-revision", body)

    def _attest(self, label: str, value: Any) -> str:
        payload = label.encode("ascii") + b"\0" + canonical_json_bytes(value)
        digest = hmac.new(self._provenance_key, payload, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def _blob_path(self, content_hash: str) -> Path:
        digest = self._hash_hex(content_hash)
        return self._safe_path("blobs", "sha256", digest[:2], digest)

    def _revision_path(self, revision_id: str) -> Path:
        digest = self._hash_hex(revision_id)
        return self._safe_path("revisions", "sha256", digest[:2], f"{digest}.json")

    @staticmethod
    def _hash_hex(value: str) -> str:
        match = _HASH_PATTERN.fullmatch(value)
        if match is None:
            raise UnsafeArtifactError("invalid sha256 reference")
        return match.group(1)

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if _ID_PATTERN.fullmatch(value) is None:
            raise UnsafeArtifactError(f"invalid {label}: {value!r}")

    @classmethod
    def _validate_artifact_type(cls, value: str) -> None:
        cls._validate_identifier(value, "artifact_type")
        normalised = (
            value.replace("_", "").replace("-", "").replace(".", "").replace(":", "").lower()
        )
        if any(part in normalised for part in _FORBIDDEN_ARTIFACT_TYPE_PARTS):
            raise UnsafeArtifactError(
                "secret, transcript, and raw model I/O artifacts are prohibited"
            )

    @classmethod
    def _assert_publishable_json(cls, value: Any, *, parent_key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                if not isinstance(raw_key, str):
                    raise UnsafeArtifactError("JSON object keys must be strings")
                key = raw_key.strip().lower()
                is_schema_name = parent_key in _SCHEMA_NAME_CONTAINERS
                if key in _FORBIDDEN_VALUE_KEYS and not is_schema_name:
                    raise UnsafeArtifactError(
                        f"sensitive or transcript field is prohibited: {raw_key}"
                    )
                cls._assert_publishable_json(child, parent_key=raw_key)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                cls._assert_publishable_json(child, parent_key=parent_key)

    def _assert_safe_content(self, content: bytes) -> None:
        for canary in self._secret_canaries:
            if canary in content:
                raise UnsafeArtifactError("known secret canary detected in artifact content")
        for label, pattern in _SENSITIVE_CONTENT_PATTERNS:
            if pattern.search(content):
                raise UnsafeArtifactError(f"{label} material detected in artifact content")
        for pattern, label in (
            (_CREDENTIAL_ASSIGNMENT, "credential-assignment"),
            (_BEARER_CREDENTIAL, "bearer-authorization"),
        ):
            for match in pattern.finditer(content):
                candidate = match.group(1).lower()
                if _is_probable_credential(candidate):
                    raise UnsafeArtifactError(
                        f"{label} material detected in artifact content"
                    )
    def _safe_path(self, *parts: str) -> Path:
        if not parts or any(
            part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts
        ):
            raise UnsafeArtifactError("unsafe artifact store path component")
        path = self._root.joinpath(*parts)
        current = self._root
        for part in parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if current.is_symlink():
                    raise UnsafeArtifactError(f"symlink path component is prohibited: {current}")
        try:
            path.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise UnsafeArtifactError("artifact path escapes store root") from exc
        return path

    def _ensure_directory(self, path: Path) -> None:
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise UnsafeArtifactError("directory escapes store root") from exc
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if current.is_symlink() or not current.is_dir():
                    raise UnsafeArtifactError(f"unsafe directory component: {current}")
                continue
            current.mkdir(mode=0o700)

    def _atomic_create(self, target: Path, content: bytes) -> bool:
        self._ensure_directory(target.parent)
        temporary = self._safe_path("tmp", f"{uuid.uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target, follow_symlinks=False)
                created = True
            except FileExistsError:
                existing = self._read_file(
                    target, missing_message=f"existing file disappeared: {target}"
                )
                if existing != content:
                    raise ArtifactIntegrityError(
                        f"immutable path already contains different bytes: {target}"
                    ) from None
                created = False
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return created
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise ArtifactStoreError(
                    f"failed to remove temporary artifact: {temporary}"
                ) from exc

    @staticmethod
    def _read_file(path: Path, *, missing_message: str) -> bytes:
        if path.is_symlink():
            raise UnsafeArtifactError(f"refusing to read symlink: {path}")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(missing_message) from exc
        except OSError as exc:
            raise UnsafeArtifactError(f"unable to safely open artifact: {path}") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            return handle.read()


__all__ = [
    "ArtifactEvent",
    "ArtifactIntegrityError",
    "ArtifactNotFoundError",
    "ArtifactRef",
    "ArtifactRevision",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactWriter",
    "ProducerCapability",
    "UnsafeArtifactError",
]

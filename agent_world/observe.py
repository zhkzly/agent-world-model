"""Read-only, secret-safe projection of a persisted Direct run."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_world.artifacts import ArtifactIntegrityError, ArtifactStore, canonical_json
from agent_world.contracts import ArtifactRef

_RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9_-]+\Z")
_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})\Z")


class ObserveError(ValueError):
    pass


def _digest_hex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DIGEST_PATTERN.fullmatch(value)
    return match.group(1) if match is not None else None


def _released_fact(
    state_root: Path, store: ArtifactStore, release: object
) -> dict[str, str] | None:
    """Re-read Registry-owned receipt and package bytes before reporting release."""

    if not isinstance(release, dict):
        return None
    package_digest = release.get("package_digest")
    receipt_digest = release.get("receipt_digest")
    package_hex = _digest_hex(package_digest)
    receipt_hex = _digest_hex(receipt_digest)
    if package_hex is None or receipt_hex is None:
        return None

    receipt_path = state_root / "registry" / "receipts" / f"{receipt_hex}.json"
    package_path = state_root / "registry" / "packages" / f"{package_hex}.zip"
    try:
        receipt_body = receipt_path.read_bytes()
        package_body = package_path.read_bytes()
        receipt = json.loads(receipt_body)
    except (OSError, json.JSONDecodeError):
        return None
    if f"sha256:{sha256(receipt_body).hexdigest()}" != receipt_digest:
        return None
    if f"sha256:{sha256(package_body).hexdigest()}" != package_digest:
        return None
    try:
        canonical_receipt = canonical_json(receipt)
    except ValueError:
        return None
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"status", "package_id", "version", "package_digest"}
        or canonical_receipt != receipt_body
        or receipt.get("status") != "released"
        or receipt.get("package_id") != release.get("package_id")
        or receipt.get("version") != release.get("version")
        or receipt.get("package_digest") != package_digest
    ):
        return None
    artifact = release.get("artifact")
    if not isinstance(artifact, dict):
        return None
    try:
        local_receipt = store.read_json(
            ArtifactRef(
                artifact_id=artifact["artifact_id"],
                kind=artifact["kind"],
                digest=artifact["digest"],
                path=artifact["path"],
                media_type=artifact["media_type"],
            )
        )
    except (ArtifactIntegrityError, KeyError, TypeError):
        return None
    if local_receipt != receipt:
        return None
    return {
        "status": "released",
        "package_id": receipt["package_id"],
        "version": receipt["version"],
        "package_digest": package_digest,
        "receipt_digest": receipt_digest,
    }


def observe_run(state_root: Path, run_id: str) -> dict[str, Any]:
    """Return safe facts only; this function never creates or changes state."""

    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ObserveError("observe_scope_not_found")
    store = ArtifactStore(state_root / "runs" / run_id)
    try:
        run = store.read_run()
    except ArtifactIntegrityError as exc:
        raise ObserveError("observe_scope_not_found") from exc

    release = (
        _released_fact(state_root, store, run.get("release"))
        if run.get("status") == "released"
        else None
    )
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "request": {
            "request_id": run.get("request_id"),
            "digest": run.get("request_digest"),
        },
        "stages": [
            {
                "stage": event.get("stage"),
                "status": event.get("status"),
                "code": event.get("code"),
                "artifact_ids": event.get("artifact_ids", []),
            }
            for event in run.get("events", [])
            if isinstance(event, dict)
        ],
        "artifacts": [
            {
                "artifact_id": item.get("artifact_id"),
                "kind": item.get("kind"),
                "digest": item.get("digest"),
            }
            for item in run.get("artifacts", [])
            if isinstance(item, dict)
        ],
        "release": release if release is not None else {"status": "not_published"},
    }

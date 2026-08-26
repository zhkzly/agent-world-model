"""Canonical payload-manifest digest behavior for the Slice 1 loader."""

from __future__ import annotations

from agent_env_foundry.release import compute_payload_digest


def test_payload_digest_is_lowercase_sha256() -> None:
    digest = compute_payload_digest({"files": []})
    assert len(digest) == 64
    int(digest, 16)
    assert digest == digest.lower()


def test_payload_digest_uses_canonical_json() -> None:
    manifest = {"files": [{"path": "a", "type": "file", "mode": 0o644, "digest": "0" * 64}]}
    reordered = {"files": [{"digest": "0" * 64, "mode": 0o644, "type": "file", "path": "a"}]}
    assert compute_payload_digest(reordered) == compute_payload_digest(manifest)


def test_payload_digest_changes_when_a_manifest_fact_changes() -> None:
    baseline = {"files": [{"path": "a", "type": "file", "mode": 0o644, "digest": "0" * 64}]}
    changed = {"files": [{"path": "a", "type": "file", "mode": 0o600, "digest": "0" * 64}]}
    assert compute_payload_digest(changed) != compute_payload_digest(baseline)

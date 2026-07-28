from __future__ import annotations

from agent_world.observability import DebugTranscriptWriter, ObservabilityRoot


def test_debug_transcripts_are_disabled_without_explicit_opt_in(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_WORLD_DEBUG_TRANSCRIPTS", raising=False)
    root = ObservabilityRoot(tmp_path / "state")
    scope_id = "generate-job:" + "a" * 24

    result = DebugTranscriptWriter(root=root).write(
        scope_id=scope_id,
        transcript="local diagnostic only",
    )

    assert result.status == "disabled"
    assert result.path is None
    assert not (root.root / scope_id / "_debug").exists()


def test_debug_transcripts_allow_one_explicit_caller_opt_in_without_environment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_WORLD_DEBUG_TRANSCRIPTS", raising=False)
    root = ObservabilityRoot(tmp_path / "state")
    scope_id = "generate-job:" + "c" * 24

    result = DebugTranscriptWriter(root=root, enabled=True).write(
        scope_id=scope_id,
        transcript="one explicitly requested local diagnostic",
    )

    assert result.status == "written"
    assert result.path is not None
    assert result.path.read_text(encoding="utf-8") == "one explicitly requested local diagnostic"


def test_debug_transcripts_reject_canaries_and_hash_sensitive_scope_ids(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_WORLD_DEBUG_TRANSCRIPTS", "1")
    canary = "phase-five-canary-secret"
    root = ObservabilityRoot(tmp_path / "state")
    writer = DebugTranscriptWriter(root=root, known_secret_canaries=(canary,))
    normal_scope = "generate-job:" + "b" * 24

    rejected = writer.write(
        scope_id=normal_scope,
        transcript=f"would leak {canary}",
    )

    assert rejected.status == "rejected"
    assert rejected.path is None
    assert not (root.root / normal_scope / "_debug").exists()

    written = writer.write(
        scope_id=canary,
        transcript="safe local-only transcript",
    )

    assert written.status == "written"
    assert written.path is not None
    assert written.path.parent.name == "_debug"
    assert written.path.parent.parent.name.startswith("sha256:")
    assert canary not in str(written.path)
    assert written.path.read_text(encoding="utf-8") == "safe local-only transcript"
    assert written.path.stat().st_mode & 0o777 == 0o600

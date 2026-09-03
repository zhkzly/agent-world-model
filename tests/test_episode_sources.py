from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.episode_sources as source_module
from agent_env_foundry.episode_sources import load_episode_sources, plan_episode_requests
from agent_env_foundry.episodes import PolicySpec
from agent_env_foundry.public_agent import PUBLIC_AGENT_PROMPT_DIGEST
from agent_env_foundry.release import canonical_bytes


def _digest(document) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(document))


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, str, str]:
    s1 = tmp_path / "s1"
    s2 = tmp_path / "s2"
    release_id = "a" * 64
    task_pack_id = "b" * 64
    structure_id = "d" * 64
    s1_campaign_id = "e" * 64
    release_path = "needs/need-a/release"
    task_path = "needs/need-a/TaskPack"
    (s1 / release_path).mkdir(parents=True)
    (s2 / task_path).mkdir(parents=True)
    record = {
        "format": "s1-v3-campaign-need-record/1",
        "campaign_id": s1_campaign_id,
        "need_id": "need-a",
        "terminal": "released",
        "release_id": release_id,
        "release_root": release_path,
    }
    _write(s1 / "records/need-a.json", {**record, "record_id": _digest(record)})
    member = {
        "need_id": "need-a",
        "release_id": release_id,
        "task_pack_id": task_pack_id,
        "structure_id": structure_id,
        "path": task_path,
    }
    corpus = {
        "format": "task-corpus-manifest/2",
        "campaign_id": "f" * 64,
        "task_pack_count": 1,
        "members": [member],
    }
    manifest_id = _digest(corpus)
    _write(s2 / "CorpusManifest.json", {**corpus, "manifest_id": manifest_id})
    return s1, s2, s1_campaign_id, manifest_id


def test_source_loader_binds_manifest_task_pack_and_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    s1, s2, s1_campaign_id, manifest_id = _fixture_roots(tmp_path)
    fake_pack = SimpleNamespace(
        task_pack_id="b" * 64,
        public_view=SimpleNamespace(task_id="c" * 64, release_id="a" * 64),
        candidate=SimpleNamespace(release_id="a" * 64, structure_id="d" * 64),
    )
    monkeypatch.setattr(source_module, "load_task_pack", lambda _path: fake_pack)
    monkeypatch.setattr(
        source_module,
        "verify_release_v3_internal",
        lambda _path: SimpleNamespace(release_id="a" * 64),
    )

    sources = load_episode_sources(
        s1,
        s2,
        expected_s1_campaign_id=s1_campaign_id,
        expected_corpus_manifest_id=manifest_id,
    )

    assert len(sources) == 1
    assert sources[0].need_id == "need-a"
    assert sources[0].release_id == "a" * 64
    assert sources[0].task_pack_id == "b" * 64
    assert sources[0].task_id == "c" * 64
    policy = PolicySpec(
        "gpt-5.6-luna",
        "openai-responses",
        "1",
        "responses:local-8317",
        PUBLIC_AGENT_PROMPT_DIGEST,
        24,
    )
    requests = plan_episode_requests(sources, policy, rollouts_per_task=8)
    assert len(requests) == 8
    assert [item.rollout_index for item in requests] == list(range(1, 9))


def test_source_loader_rejects_cross_release_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    s1, s2, s1_campaign_id, manifest_id = _fixture_roots(tmp_path)
    fake_pack = SimpleNamespace(
        task_pack_id="b" * 64,
        public_view=SimpleNamespace(task_id="c" * 64, release_id="9" * 64),
        candidate=SimpleNamespace(release_id="9" * 64, structure_id="d" * 64),
    )
    monkeypatch.setattr(source_module, "load_task_pack", lambda _path: fake_pack)
    monkeypatch.setattr(
        source_module,
        "verify_release_v3_internal",
        lambda _path: SimpleNamespace(release_id="a" * 64),
    )

    with pytest.raises(ValueError, match="binding"):
        load_episode_sources(
            s1,
            s2,
            expected_s1_campaign_id=s1_campaign_id,
            expected_corpus_manifest_id=manifest_id,
        )

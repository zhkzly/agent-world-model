from __future__ import annotations

from types import SimpleNamespace

from agent_env_foundry.builder import BuilderConfig
from agent_env_foundry.task_proposal import ProposalFailure
from agent_env_foundry.task_sampler import sample_good_tasks


class Document(SimpleNamespace):
    def to_document(self):
        return dict(self.document)


def test_sampler_rejects_one_candidate_then_continues_without_pressure_pipeline(
    tmp_path, monkeypatch
) -> None:
    calls = 0

    def propose(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProposalFailure("CandidateRejected", "not_solved", "no executed solution")
        return SimpleNamespace(
            candidate=Document(candidate_id="2" * 64, document={"candidate": True}),
            evidence=Document(document={"evidence": True}),
        )

    task = Document(
        task_id="3" * 64,
        release_id="1" * 64,
        checker_project_digest="4" * 64,
        document={"task": True},
    )
    checker = SimpleNamespace(
        root=tmp_path / "checker",
        task_contract=task,
    )
    sanity_calls = []
    witness_indices = []
    monkeypatch.setattr("agent_env_foundry.task_sampler.propose_task_direct", propose)
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler.prepare_checker_author_workspace",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler.run_checker_author",
        lambda *args, **kwargs: checker,
    )
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler._checker_sanity",
        lambda *args, **kwargs: sanity_calls.append(kwargs["task"].task_id),
    )

    def solve(*args, witness_index, **kwargs):
        witness_indices.append(witness_index)
        return {
            "format": "task-witness/1",
            "witness_index": witness_index,
            "witness_id": str(witness_index) * 64,
        }

    monkeypatch.setattr("agent_env_foundry.task_sampler._fresh_solve", solve)
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler.copy_authored_project",
        lambda *args, **kwargs: "4" * 64,
    )
    prepared = SimpleNamespace(identity=SimpleNamespace(release_id="1" * 64))

    report = sample_good_tasks(
        prepared,
        development_brief={"need": "Sample Tasks."},
        research_digest="5" * 64,
        output_root=tmp_path / "sampling",
        candidate_budget=2,
        target_count=1,
        checker_config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert report["accepted_count"] == 1
    assert report["rejected_count"] == 1
    assert report["attempts"][0]["code"] == "not_solved"
    assert report["attempts"][1]["task_pack_id"]
    assert sanity_calls == ["3" * 64]
    assert witness_indices == [1, 2]
    assert (tmp_path / "sampling/DirectSamplingReport.json").is_file()
    assert not {
        "partial",
        "wrong_target",
        "collateral",
        "challenge_categories",
    } & set(str(report))

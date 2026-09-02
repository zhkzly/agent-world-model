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
            candidate=Document(
                candidate_id="2" * 64,
                reset_start=None,
                final_answer_schema={"type": "object", "properties": {}},
                document={"candidate": True},
            ),
            evidence=Document(
                public_trace=({"tool": "inspect", "arguments": {}, "observation": {}},),
                before_state={"value": 0},
                after_state={"value": 1},
                document={"evidence": True},
            ),
            provider_turns=2,
            usage=({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},),
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
            "provider_turns": 3,
            "public_trace": [{"tool": "inspect"}, {"tool": "mutate"}],
            "usage": [{"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}],
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
        builder_projection_digest="5" * 64,
        output_root=tmp_path / "sampling",
        candidate_budget=2,
        target_count=1,
        checker_config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert report["accepted_count"] == 1
    assert report["rejected_count"] == 1
    assert report["attempts"][0]["code"] == "not_solved"
    assert report["attempts"][1]["task_pack_id"]
    assert report["attempts"][1]["proposal_provider_turns"] == 2
    assert report["attempts"][1]["proposal_tool_calls"] == 1
    assert report["attempts"][1]["witness_provider_turns"] == [3, 3]
    assert report["attempts"][1]["witness_tool_calls"] == [2, 2]
    assert report["attempts"][1]["provider_usage"]["proposal"][0]["total_tokens"] == 15
    assert set(report["attempts"][1]["stage_elapsed_ms"]) == {
        "proposal",
        "dedup",
        "checker",
        "checker_sanity",
        "fresh_solve",
        "package",
    }
    assert report["attempts"][1]["elapsed_ms"] >= 0
    assert sanity_calls == ["3" * 64]
    assert witness_indices == [1, 2]
    assert (tmp_path / "sampling/DirectSamplingReport.json").is_file()
    assert not {
        "partial",
        "wrong_target",
        "collateral",
        "challenge_categories",
    } & set(str(report))


def test_sampler_without_target_exhausts_budget_and_deduplicates_before_checker(
    tmp_path, monkeypatch
) -> None:
    proposed_tools = iter(("inspect", "inspect", "mutate"))
    proposal_index = 0

    def propose(*args, **kwargs):
        nonlocal proposal_index
        proposal_index += 1
        tool = next(proposed_tools)
        return SimpleNamespace(
            candidate=Document(
                candidate_id=str(proposal_index) * 64,
                reset_start=None,
                final_answer_schema={
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                },
                document={"candidate": proposal_index},
            ),
            evidence=Document(
                public_trace=({"tool": tool, "arguments": {}, "observation": {}},),
                before_state={"value": 0},
                after_state={"value": 1},
                document={"evidence": proposal_index},
            ),
            provider_turns=1,
            usage=(None,),
        )

    checker_calls = 0

    def checker(*args, **kwargs):
        nonlocal checker_calls
        checker_calls += 1
        return SimpleNamespace(
            root=tmp_path / f"checker-{checker_calls}",
            task_contract=Document(
                task_id=str(checker_calls + 5) * 64,
                release_id="1" * 64,
                checker_project_digest="4" * 64,
                document={"task": checker_calls},
            ),
        )

    monkeypatch.setattr("agent_env_foundry.task_sampler.propose_task_direct", propose)
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler.prepare_checker_author_workspace",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr("agent_env_foundry.task_sampler.run_checker_author", checker)
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler._checker_sanity",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler._fresh_solve",
        lambda *args, witness_index, **kwargs: {
            "format": "task-witness/1",
            "witness_index": witness_index,
            "witness_id": str(witness_index) * 64,
            "provider_turns": 1,
            "public_trace": [{"tool": "solve"}],
            "usage": [None],
        },
    )
    monkeypatch.setattr(
        "agent_env_foundry.task_sampler.copy_authored_project",
        lambda *args, **kwargs: "4" * 64,
    )
    prepared = SimpleNamespace(identity=SimpleNamespace(release_id="1" * 64))

    report = sample_good_tasks(
        prepared,
        development_brief={"need": "Sample every unique Task."},
        builder_projection_digest="5" * 64,
        output_root=tmp_path / "sampling",
        candidate_budget=3,
        target_count=None,
        checker_config=BuilderConfig(uv_cache_dir=tmp_path / "uv-cache"),
    )

    assert len(report["attempts"]) == 3
    assert report["target_count"] is None
    assert report["accepted_count"] == 2
    assert report["rejected_count"] == 1
    assert report["attempts"][1]["code"] == "duplicate_task_structure"
    assert checker_calls == 2
    assert len(tuple((tmp_path / "sampling/packs").iterdir())) == 2
